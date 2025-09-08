from fastapi import APIRouter, Depends, status
from sqlalchemy.orm import Session
from db.session import get_db
from core.categories import category_service
from schemas.categories import CategoryCreate

router = APIRouter()


@router.post("/", status_code=status.HTTP_201_CREATED)
def create_category(payload: CategoryCreate, db: Session = Depends(get_db)):
    category = category_service.add_category(
        db=db,
        name=payload.name,
        description=payload.description
    )
    return {
        "success": True,
        "message": "Category created successfully",
        "data": category
    }
