from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from core.products import product_service
from db.session import get_db
from core.auth import role_required

router = APIRouter()


@router.get("/")
def list_products(db: Session = Depends(get_db)):
    try:
        products = product_service.fetch_products(db)
        return products
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(e))


@router.get("/{product_id}")
def get_product_by_id(product_id: str, db: Session = Depends(get_db)):
    try:
        product = product_service.get_product_by_id(
            db=db, product_id=product_id)
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(e))


@router.get("/{seller_id}")
def get_products_by_seller(seller_id: str, db: Session = Depends(get_db)):
    try:
        products = product_service.get_products_by_seller(
            db=db, seller_id=seller_id)
        return products
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(e))


@router.get("/{category_id}")
def get_products_by_category(category_id: str, db: Session = Depends(get_db)):
    try:
        products = product_service.get_products_by_category(
            db=db, category_id=category_id)
        return products
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(e))


@router.delete("/{product_id}")
def delete_product(product_id: str,  user=Depends(role_required(["admin", "seller"])), db: Session = Depends(get_db),):
    try:
        user_id = user["id"]
        product = product_service.get_product_by_id(
            db=db, product_id=product_id)
        if not product:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="Product not found")
        db.delete(product)
        db.commit()
        return {"detail": "Product deleted successfully"}
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(e))
