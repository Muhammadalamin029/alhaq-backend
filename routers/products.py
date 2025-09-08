from fastapi import APIRouter, Depends, status, HTTPException
from sqlalchemy.orm import Session
from core.products import product_service
from db.session import get_db
from core.auth import role_required
from schemas.products import ProductCreate, ProductResponse

router = APIRouter()

# 0ae50041-f371-4daf-b4f5-f5c0ded517fa


@router.get("/")
def list_products(db: Session = Depends(get_db)):
    products = product_service.fetch_products(db)
    return {
        "success": True,
        "message": "Products fetched successfully",
        "data": [ProductResponse.model_validate(p) for p in products] if products else []
    }


@router.post("/")
def add_product(payload: ProductCreate, user=Depends(role_required(["admin", "seller"])), db: Session = Depends(get_db)):
    new_product = product_service.add_product(
        db=db,
        name=payload.name,
        price=payload.price,
        user_id=user["id"],
        category_id=payload.category_id,
        description=payload.description,
        stock_quantity=payload.stock_quantity,
        image_url=payload.image_url
    )

    if not new_product:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Failed to create product"
        )

    return {
        "success": True,
        "message": "Product created successfully",
        "data": new_product
    }


@router.get("/id/{product_id}")
def get_product_by_id(product_id: str, db: Session = Depends(get_db)):
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
def get_products_by_seller(seller_id: str, db: Session = Depends(get_db)):
    products = product_service.get_products_by_seller(
        db=db, seller_id=seller_id)
    if not products:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No products found for this seller"
        )
    return {
        "success": True,
        "message": "Products fetched successfully",
        "data": [ProductResponse.model_validate(p) for p in products] if products else []
    }


@router.get("/category/{category_id}")
def get_products_by_category(category_id: str, db: Session = Depends(get_db)):
    products = product_service.get_products_by_category(
        db=db, category_id=category_id)
    if not products:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No products found for this category"
        )
    return {
        "success": True,
        "message": "Products fetched successfully",
        "data": [ProductResponse.model_validate(p) for p in products] if products else []
    }


@router.delete("/{product_id}")
def delete_product(
    product_id: str,
    user=Depends(role_required(["admin", "seller"])),
    db: Session = Depends(get_db),
):
    product = product_service.get_product_by_id(db=db, product_id=product_id)
    if not product:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Product not found"
        )

    db.delete(product)
    db.commit()
    return {
        "success": True,
        "message": "Product deleted successfully",
        "data": None
    }
