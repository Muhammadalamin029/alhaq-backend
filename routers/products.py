from fastapi import APIRouter, Depends, status, HTTPException, Query
from sqlalchemy.orm import Session
from core.products import product_service
from core.model import Product, ProductImage
from db.session import get_db
from core.auth import role_required
from schemas.products import ProductCreate, ProductResponse, ProductUpdate
from typing import Optional
from core.logging_config import get_logger, log_error

# Get logger for products routes
products_logger = get_logger("routers.products")

router = APIRouter()


@router.get("/")
async def list_products(
    db: Session = Depends(get_db),
    page: int = Query(1, ge=1, description="Page number"),
    limit: int = Query(10, ge=1, le=100, description="Items per page"),
    search_query: Optional[str] = Query(
        None, description="Search products by name"),
    category_id: Optional[str] = Query(None, description="Filter by category"),
):
    try:
        products_logger.info(f"Fetching products - page: {page}, limit: {limit}, search: {search_query}, category: {category_id}")
        
        products, count = product_service.fetch_products(
            db=db, limit=limit, page=page, category_id=category_id, search_query=search_query)
        
        products_logger.info(f"Products fetched successfully - count: {count}, page: {page}")
        
        return {
            "success": True,
            "message": "Products fetched successfully",
            "data": [ProductResponse.model_validate(p) for p in products] if products else [],
            "pagination": {
                "page": page,
                "limit": limit,
                "total": count,
                "total_pages": (count + limit - 1) // limit
            }
        }
    except Exception as e:
        log_error(products_logger, "Failed to fetch products", e, page=page, limit=limit, search_query=search_query, category_id=category_id)
        raise HTTPException(status_code=500, detail="Failed to fetch products")


@router.post("/", status_code=status.HTTP_201_CREATED)
async def add_product(payload: ProductCreate, user=Depends(role_required(["admin", "seller"])), db: Session = Depends(get_db)):
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
    
    # Validate product name is unique for this seller (optional business rule)
    existing_product = db.query(Product).filter(
        Product.seller_id == user["id"],
        Product.name == payload.name
    ).first()
    if existing_product:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="You already have a product with this name"
        )
    
    try:
        products_logger.info(f"Creating new product: {payload.name} by user {user['id']}")
        
        new_product = product_service.add_product(
            db=db,
            name=payload.name,
            price=payload.price,
            user_id=user["id"],
            category_id=payload.category_id,
            description=payload.description,
            stock_quantity=payload.stock_quantity,
            images=payload.images
        )

        if not new_product:
            products_logger.error(f"Product creation failed for user {user['id']}: service returned None")
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Failed to create product"
            )
        
        products_logger.info(f"Product created successfully: {new_product.id} by user {user['id']}")
        
        return {
            "success": True,
            "message": "Product created successfully",
            "data": ProductResponse.model_validate(new_product)
        }
    except HTTPException:
        raise
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
    product = product_service.get_product_by_id(db=db, product_id=product_id)
    if not product:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Product not found"
        )
    return {
        "success": True,
        "message": "Product fetched successfully",
        "data": ProductResponse.model_validate(product)
    }


@router.put("/{product_id}")
async def update_product(
    product_id: str,
    payload: ProductUpdate,
    user=Depends(role_required(["admin", "seller"])),
    db: Session = Depends(get_db)
):
    """Update a product"""
    # First check if product exists
    product = product_service.get_product_by_id(db, product_id)
    if not product:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Product not found"
        )
    
    # Check if user owns the product (unless admin)
    if user["role"] == "seller" and str(product.seller_id) != user["id"]:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You can only update your own products"
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
        
        # Handle product images update if provided
        if "images" in update_data and update_data["images"] is not None:
            products_logger.info(f"Updating images for product {product_id}")
            try:
                # Remove existing images
                db.query(ProductImage).filter(ProductImage.product_id == product_id).delete()
                
                # Add new images
                for img in update_data["images"]:
                    new_image = ProductImage(
                        product_id=product_id,
                        image_url=img["image_url"]
                    )
                    db.add(new_image)
                
                # Remove images from update_data as it's handled separately
                del update_data["images"]
                products_logger.info(f"Images updated successfully for product {product_id}")
            except Exception as image_error:
                products_logger.error(f"Error updating images for product {product_id}: {str(image_error)}")
                raise image_error
        
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
        
        return {
            "success": True,
            "message": "Product updated successfully",
            "data": ProductResponse.model_validate(updated_product)
        }
        
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
    user=Depends(role_required(["admin", "seller"])),
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
    
    # Check if user owns the product (unless admin)
    if user["role"] == "seller" and str(product.seller_id) != user["id"]:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You can only update your own products"
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


@router.get("/seller/{seller_id}")
async def get_products_by_seller(
        seller_id: str,
        page: int = Query(1, ge=1, description="Page number"),
        limit: int = Query(10, ge=1, le=100, description="Items per page"),
        db: Session = Depends(get_db)):

    products, count = product_service.get_products_by_seller(
        db=db, seller_id=seller_id, limit=limit, page=page)

    return {
        "success": True,
        "message": "Products fetched successfully",
        "data": [ProductResponse.model_validate(p) for p in products] if products else [],
        "pagination": {
            "page": page,
            "limit": limit,
            "total": count,
            "total_pages": (count + limit - 1) // limit
        }
    }


@router.delete("/{product_id}")
async def delete_product(
    product_id: str,
    user=Depends(role_required(["admin", "seller"])),
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
    
    # Check if user owns the product (unless admin)
    if user["role"] == "seller" and str(product.seller_id) != user["id"]:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You can only delete your own products"
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

    success = product_service.delete_product(db=db, product_id=product_id)
    if not success:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to delete product"
        )

    return {
        "success": True,
        "message": "Product deleted successfully",
        "data": None
    }
