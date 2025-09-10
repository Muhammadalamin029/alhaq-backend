from fastapi import APIRouter, Depends, status, HTTPException, Query
from sqlalchemy.orm import Session
from core.products import product_service
from db.session import get_db
from core.auth import role_required
from schemas.products import ProductCreate, ProductResponse
from typing import Optional

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
    products, count = product_service.fetch_products(
        db=db, limit=limit, page=page, category_id=category_id, search_query=search_query)

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


@router.post("/")
async def add_product(payload: ProductCreate, user=Depends(role_required(["admin", "seller"])), db: Session = Depends(get_db)):
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
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Failed to create product"
        )

    return {
        "success": True,
        "message": "Product created successfully",
        "data": ProductResponse.model_validate(new_product)
    }


@router.get("/id/{product_id}")
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


@router.get("/seller/{seller_id}")
async def get_products_by_seller(
        seller_id: str,
        page: int = Query(1, ge=1, description="Page number"),
        limit: int = Query(10, ge=1, le=100, description="Items per page"),
        db: Session = Depends(get_db)):

    products, count = product_service.get_products_by_seller(
        db=db, seller_id=seller_id, limit=limit, page=page)

    if not products:
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
    # Check if user owns the product (unless admin)
    if user["role"] == "seller":
        product = product_service.get_product_by_id(db, product_id)
        if not product or str(product.seller_id) != user["id"]:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="You can only delete your own products"
            )

    success = product_service.delete_product(db=db, product_id=product_id)
    if not success:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Product not found"
        )

    return {
        "success": True,
        "message": "Product deleted successfully",
        "data": None
    }
