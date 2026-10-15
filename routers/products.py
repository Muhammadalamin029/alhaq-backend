from fastapi import APIRouter, Depends, status, HTTPException, Query
from sqlalchemy.orm import Session
from core.products import product_service
from core.model import Product, AssetImage
from db.session import get_db
from core.auth import role_required
from core.store_service import get_store_id
from schemas.products import ProductCreate, ProductResponse, ProductUpdate
from typing import Optional
from core.logging_config import get_logger, log_error
from core.system_settings_service import system_settings_service
from core import product_cache

# Get logger for products routes
products_logger = get_logger("routers.products")

router = APIRouter()


def _resolve_nl_category(db: Session, hint: str):
    """Map a parser category hint onto a real category id.

    Matches exact, plural-insensitive, then substring. Returns None when
    no category matches so the keyword path still applies.
    """
    try:
        from core.categories import category_service

        norm = (hint or "").strip().lower()
        if not norm:
            return None
        categories, _ = category_service.fetch_categories(db, limit=100, page=1)
        if not categories:
            return None

        def singular(s: str) -> str:
            return s[:-1] if s.endswith("s") and len(s) > 3 else s

        names = [(c, (c.name or "").strip().lower()) for c in categories]
        for c, name in names:
            if name == norm:
                return str(c.id)
        for c, name in names:
            if singular(name) == singular(norm):
                return str(c.id)
        for c, name in names:
            if norm in name or name in norm:
                return str(c.id)
        return None
    except Exception:
        return None


@router.get("/")
async def list_products(
    db: Session = Depends(get_db),
    page: int = Query(1, ge=1, description="Page number"),
    limit: int = Query(10, ge=1, le=100, description="Items per page"),
    search_query: Optional[str] = Query(
        None, description="Search products by name"),
    category_id: Optional[str] = Query(None, description="Filter by category"),
    min_price: Optional[float] = Query(None, ge=0, description="Minimum price"),
    max_price: Optional[float] = Query(None, ge=0, description="Maximum price"),
    status: Optional[str] = Query(None, description="Filter by status"),
    sort_by: Optional[str] = Query(None, description="Sort field: price, name, created_at"),
    sort_order: Optional[str] = Query(None, description="Sort direction: asc, desc"),
):
    try:
        products_logger.info(f"Fetching products - page: {page}, limit: {limit}, search: {search_query}, category: {category_id}")

        # Use a reasonable limit to prevent excessive data loading
        effective_limit = min(limit, 50)  # Cap at 50 products per request

        # Search queries bypass Redis (low hit rate, cache-buster on FE anyway)
        # Parser-first: a natural-language query is reduced to structured
        # filters before the normal keyword path runs. Non-NL input and
        # explicit query params are never overridden.
        effective_search_query = search_query
        effective_category_id = category_id
        effective_min_price = min_price
        effective_max_price = max_price
        effective_sort_by = sort_by
        effective_sort_order = sort_order
        applied_filters = None
        if search_query and search_query.strip():
            try:
                from core.nl_search_parser import parse_search_query

                parsed = parse_search_query(search_query)
            except Exception as e:
                products_logger.warning(
                    f"NL parser failed, falling back to keyword search: {e}"
                )
                parsed = None
            if parsed is not None and parsed.was_nl:
                if parsed.clean_query is not None:
                    effective_search_query = parsed.clean_query or None
                if effective_category_id is None and parsed.category_hint:
                    effective_category_id = _resolve_nl_category(db, parsed.category_hint)
                if effective_min_price is None and parsed.min_price is not None:
                    effective_min_price = parsed.min_price
                if effective_max_price is None and parsed.max_price is not None:
                    effective_max_price = parsed.max_price
                if effective_sort_by is None and parsed.sort_by is not None:
                    effective_sort_by = parsed.sort_by
                    if effective_sort_order is None:
                        effective_sort_order = parsed.sort_order
                applied_filters = {
                    "was_nl": True,
                    "clean_query": effective_search_query,
                    "category_id": effective_category_id,
                    "min_price": effective_min_price,
                    "max_price": effective_max_price,
                    "sort_by": effective_sort_by,
                    "sort_order": effective_sort_order,
                }
                products_logger.info(
                    f"NL search parsed: {search_query!r} -> {applied_filters}"
                )

        cache_key = None
        if not search_query:
            cache_key = product_cache.build_list_key(
                page=page, limit=effective_limit, category_id=effective_category_id,
                min_price=effective_min_price, max_price=effective_max_price, status=status,
                sort_by=effective_sort_by, sort_order=effective_sort_order,
            )
            cached = await product_cache.get_list(cache_key)
            if cached is not None:
                products_logger.debug(f"Products list cache hit - page: {page}")
                return cached

        products, count = product_service.fetch_products(
            db=db, limit=effective_limit, page=page, category_id=effective_category_id, search_query=effective_search_query,
            min_price=effective_min_price, max_price=effective_max_price, status=status, sort_by=effective_sort_by, sort_order=effective_sort_order)

        products_logger.info(f"Products fetched successfully - count: {count}, page: {page}")

        response = {
            "success": True,
            "message": "Products fetched successfully",
            "data": [ProductResponse.with_discount(p).model_dump(mode="json") for p in products] if products else [],
            "applied_filters": applied_filters,
            "pagination": {
                "page": page,
                "limit": effective_limit,
                "total": count,
                "total_pages": (count + effective_limit - 1) // effective_limit
            }
        }
        if cache_key:
            await product_cache.set_list(cache_key, response)
        return response
    except Exception as e:
        log_error(products_logger, "Failed to fetch products", e, page=page, limit=limit, search_query=search_query, category_id=category_id, min_price=min_price, max_price=max_price, status=status, sort_by=sort_by, sort_order=sort_order)
        raise HTTPException(status_code=500, detail="Failed to fetch products")


@router.post("/", status_code=status.HTTP_201_CREATED)
async def add_product(payload: ProductCreate, user=Depends(role_required(["admin"])), db: Session = Depends(get_db)):
    system_settings_service.require_verified_email_for_user(db, user["id"], "create a product")

    # Validate price is positive
    if payload.price <= 0:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Product price must be greater than 0"
        )

    # Validate stock quantity is non-negative
    if payload.stock_quantity < 0:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Stock quantity cannot be negative"
        )

    # Validate category exists
    from core.categories import category_service
    category = category_service.get_category_by_id(db, payload.category_id)
    if not category:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Category not found"
        )

    store_id = get_store_id(db)

    # Validate product name is unique (optional business rule)
    existing_product = db.query(Product).filter(
        Product.seller_id == store_id,
        Product.name == payload.name
    ).first()
    if existing_product:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="A product with this name already exists"
        )

    try:
        products_logger.info(f"Creating new product: {payload.name} by user {user['id']}")

        new_product = product_service.add_product(
            db=db,
            name=payload.name,
            price=payload.price,
            user_id=store_id,
            category_id=payload.category_id,
            description=payload.description,
            stock_quantity=payload.stock_quantity,
            amenities=payload.amenities,
            images=payload.images,
            discount_percent=payload.discount_percent,
            sale_price=payload.sale_price,
            discount_starts_at=payload.discount_starts_at,
            discount_ends_at=payload.discount_ends_at,
        )

        if not new_product:
            products_logger.error(f"Product creation failed for user {user['id']}: service returned None")
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Failed to create product"
            )
        
        products_logger.info(f"Product created successfully: {new_product.id} by user {user['id']}")
        await product_cache.invalidate_product(str(new_product.id))
        
        return {
            "success": True,
            "message": "Product created successfully",
            "data": ProductResponse.with_discount(new_product)
        }
    except HTTPException:
        raise
    except ValueError as e:
        db.rollback()
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))
    except Exception as e:
        db.rollback()
        log_error(products_logger, f"Failed to create product for user {user['id']}", e, 
                  user_id=user['id'], product_name=payload.name, price=payload.price)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="An error occurred while creating the product"
        )


@router.get("/{product_id}")
async def get_product_by_id(product_id: str, db: Session = Depends(get_db)):
    cached = await product_cache.get_detail(product_id)
    if cached is not None:
        return cached
    product = product_service.get_product_by_id(db=db, product_id=product_id)
    if not product:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Product not found"
        )
    response = {
        "success": True,
        "message": "Product fetched successfully",
        "data": ProductResponse.with_discount(product).model_dump(mode="json")
    }
    await product_cache.set_detail(product_id, response)
    return response


@router.put("/{product_id}")
async def update_product(
    product_id: str,
    payload: ProductUpdate,
    user=Depends(role_required(["admin"])),
    db: Session = Depends(get_db)
):
    """Update a product"""
    system_settings_service.require_verified_email_for_user(db, user["id"], "update a product")

    # First check if product exists
    product = product_service.get_product_by_id(db, product_id)
    if not product:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Product not found"
        )

    # Get update data and validate
    update_data = payload.model_dump(exclude_unset=True)
    if not update_data:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="No fields provided for update"
        )
    
    # Validate individual fields if they're being updated
    if "price" in update_data and update_data["price"] <= 0:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Product price must be greater than 0"
        )
    
    if "stock_quantity" in update_data and update_data["stock_quantity"] < 0:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Stock quantity cannot be negative"
        )
    
    # Validate category exists if category is being updated
    if "category_id" in update_data:
        from core.categories import category_service
        category = category_service.get_category_by_id(db, update_data["category_id"])
        if not category:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Category not found"
            )
    
    # Validate discount window when both ends supplied
    if "discount_starts_at" in update_data and "discount_ends_at" in update_data:
        s, e = update_data["discount_starts_at"], update_data["discount_ends_at"]
        if s is not None and e is not None and e <= s:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Discount end must be after discount start"
            )

    # Validate product name uniqueness for this seller (if name is being updated)
    if "name" in update_data:
        existing_product = db.query(Product).filter(
            Product.seller_id == product.seller_id,
            Product.name == update_data["name"],
            Product.id != product_id
        ).first()
        if existing_product:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="You already have a product with this name"
            )
    
    # Check if product has pending orders before allowing status change to inactive
    if "status" in update_data and update_data["status"] == "inactive":
        from core.model import Order, OrderItem
        pending_orders = db.query(Order).join(OrderItem).filter(
            OrderItem.product_id == product_id,
            Order.status.in_(["pending", "processing"])
        ).first()
        
        if pending_orders:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Cannot deactivate product with pending or processing orders"
            )
    
    try:
        # Debug logging
        products_logger.info(f"Updating product {product_id} with data: {update_data}")
        
        # Update the product
        products_logger.info(f"Calling product_service.update_product with: {update_data}")
        try:
            updated_product = product_service.update_product(
                db=db, product_id=product_id, **update_data
            )
            
            if updated_product:
                products_logger.info(f"Product {product_id} updated successfully: {updated_product.name}")
            else:
                products_logger.error(f"Product {product_id} update returned None")
        except Exception as update_error:
            products_logger.error(f"Error in product_service.update_product: {str(update_error)}")
            products_logger.error(f"Update data: {update_data}")
            raise update_error
        
        if not updated_product:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Failed to update product"
            )
        await product_cache.invalidate_product(str(product_id))
        
        return {
            "success": True,
            "message": "Product updated successfully",
            "data": ProductResponse.with_discount(updated_product)
        }
        
    except HTTPException:
        raise
    except ValueError as e:
        db.rollback()
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))
    except Exception as e:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="An error occurred while updating the product"
        )


@router.patch("/{product_id}/stock")
async def update_product_stock(
    product_id: str,
    stock_quantity: int = Query(..., ge=0, description="New stock quantity"),
    user=Depends(role_required(["admin"])),
    db: Session = Depends(get_db)
):
    """Update product stock quantity only"""
    # First check if product exists
    product = product_service.get_product_by_id(db, product_id)
    if not product:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Product not found"
        )

    try:
        # Update stock using the service method
        updated_product = product_service.update_product_stock(
            db=db, product_id=product_id, new_stock=stock_quantity
        )
        
        if not updated_product:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Failed to update product stock"
            )
        await product_cache.invalidate_product(str(product_id))
        
        return {
            "success": True,
            "message": "Product stock updated successfully",
            "data": {
                "product_id": product_id,
                "new_stock_quantity": stock_quantity,
                "previous_stock_quantity": product.stock_quantity
            }
        }
        
    except Exception as e:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="An error occurred while updating the product stock"
        )


@router.delete("/{product_id}")
async def delete_product(
    product_id: str,
    user=Depends(role_required(["admin"])),
    db: Session = Depends(get_db),
):
    """Delete a product"""
    # First check if product exists
    product = product_service.get_product_by_id(db, product_id)
    if not product:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Product not found"
        )

    # Check if product has pending orders (prevent deletion)
    from core.model import Order, OrderItem
    pending_orders = db.query(Order).join(OrderItem).filter(
        OrderItem.product_id == product_id,
        Order.status.in_(["pending", "processing"])
    ).first()
    
    if pending_orders:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Cannot delete product with pending or processing orders"
        )

    # Check if product has any order history
    existing_order_items = db.query(OrderItem).filter(OrderItem.product_id == product_id).first()
    
    success = product_service.delete_product(db=db, product_id=product_id)
    if not success:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to delete product"
        )
    await product_cache.invalidate_product(str(product_id))

    # Determine the appropriate response message
    if existing_order_items:
        message = "Product marked as inactive due to existing order history. Product data preserved for financial records."
    else:
        message = "Product deleted successfully"

    return {
        "success": True,
        "message": message,
        "data": None
    }
