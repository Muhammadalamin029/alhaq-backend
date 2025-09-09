from fastapi import APIRouter, Depends, status, HTTPException
from sqlalchemy.orm import Session
from core.products import product_service
from db.session import get_db
from core.auth import role_required
from schemas.products import ProductCreate, ProductResponse

router = APIRouter()


@router.get("/")
async def list_products(search_query: str = None, db: Session = Depends(get_db)):
    if search_query:
        products = product_service.search_products(db, search_query)
    else:
        products = product_service.fetch_products(db)
    return {
        "success": True,
        "message": "Products fetched successfully",
        "data": [ProductResponse.model_validate(p) for p in products] if products else []
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
async def get_products_by_seller(seller_id: str, db: Session = Depends(get_db)):
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
async def get_products_by_category(category_id: str, db: Session = Depends(get_db)):
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
async def delete_product(
    product_id: str,
    user=Depends(role_required(["admin", "seller", "customer"])),
    db: Session = Depends(get_db),
):
    product = product_service.delete_product(db=db, product_id=product_id)
    if not product:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Product not found"
        )

    return {
        "success": True,
        "message": "Product deleted successfully",
        "data": None
    }
