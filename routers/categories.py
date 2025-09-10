from fastapi import APIRouter, Depends, status
from sqlalchemy.orm import Session
from db.session import get_db
from core.categories import category_service
from schemas.categories import CategoryCreate, CategoryResponse
from core.auth import role_required

router = APIRouter()


@router.get("/")
async def list_categories(db: Session = Depends(get_db)):
    categories = category_service.fetch_categories(db=db)

    return {
        "success": True,
        "message": "Categories fetched successfully",
        "data": [CategoryResponse.model_validate(c) for c in categories] if categories else []
    }


@router.post("/", status_code=status.HTTP_201_CREATED)
async def create_category(payload: CategoryCreate, user=Depends(role_required(["admin"])), db: Session = Depends(get_db)):
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
