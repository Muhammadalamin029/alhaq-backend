from fastapi import APIRouter, Depends, HTTPException, status, Query
from sqlalchemy.orm import Session
from sqlalchemy.exc import IntegrityError
from db.session import get_db
from core.categories import category_service
from schemas.categories import CategoryCreate, CategoryResponse, CategoryUpdate
from core.auth import role_required
from core.logging_config import get_logger, log_error

# Get logger for categories routes
categories_logger = get_logger("routers.categories")

router = APIRouter()


@router.get("/")
async def list_categories(
    db: Session = Depends(get_db),
    page: int = Query(1, ge=1, description="Page number"),
    limit: int = Query(10, ge=1, le=100, description="Items per page")
):
    categories, count = category_service.fetch_categories(db=db, limit=limit, page=page)

    return {
        "success": True,
        "message": "Categories fetched successfully",
        "data": [CategoryResponse.model_validate(c) for c in categories] if categories else [],
        "pagination": {
            "page": page,
            "limit": limit,
            "total": count,
            "total_pages": (count + limit - 1) // limit
        }
    }


@router.get("/{category_id}")
async def get_category(category_id: str, db: Session = Depends(get_db)):
    category = category_service.get_category_by_id(db=db, category_id=category_id)
    if not category:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Category not found"
        )
    return {
        "success": True,
        "message": "Category fetched successfully",
        "data": CategoryResponse.model_validate(category)
    }


@router.post("/", status_code=status.HTTP_201_CREATED)
async def create_category(
    payload: CategoryCreate, 
    user=Depends(role_required(["admin"])), 
    db: Session = Depends(get_db)
):
    try:
        categories_logger.info(f"Creating new category: {payload.name} by user {user['id']}")
        
        category = category_service.add_category(
            db=db,
            name=payload.name,
            description=payload.description
        )
        
        categories_logger.info(f"Category created successfully: {category.id} by user {user['id']}")
        
        return {
            "success": True,
            "message": "Category created successfully",
            "data": CategoryResponse.model_validate(category)
        }
    except ValueError as e:
        categories_logger.warning(f"Invalid category data from user {user['id']}: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e)
        )
    except IntegrityError as e:
        db.rollback()
        categories_logger.warning(f"Duplicate category name attempt by user {user['id']}: {payload.name}")
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Category name already exists"
        )
    except Exception as e:
        db.rollback()
        log_error(categories_logger, f"Failed to create category for user {user['id']}", e, 
                  user_id=user['id'], category_name=payload.name)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to create category"
        )


@router.put("/{category_id}")
async def update_category(
    category_id: str,
    payload: CategoryUpdate,
    user=Depends(role_required(["admin"])),
    db: Session = Depends(get_db)
):
    # Check if category exists
    existing_category = category_service.get_category_by_id(db=db, category_id=category_id)
    if not existing_category:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Category not found"
        )
    
    # Prepare update data
    update_data = payload.model_dump(exclude_unset=True)
    if not update_data:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="No fields provided for update"
        )
    
    try:
        # Check for duplicate name if name is being updated
        if "name" in update_data:
            existing_name = category_service.get_category_by_name(db, update_data["name"])
            if existing_name and str(existing_name.id) != category_id:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Category name already exists"
                )
        
        updated_category = category_service.update_category(
            db=db, category_id=category_id, **update_data
        )
        
        return {
            "success": True,
            "message": "Category updated successfully",
            "data": CategoryResponse.model_validate(updated_category)
        }
    except IntegrityError:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Category name already exists"
        )
    except Exception:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to update category"
        )


@router.delete("/{category_id}")
async def delete_category(
    category_id: str,
    user=Depends(role_required(["admin"])),
    db: Session = Depends(get_db)
):
    # Check if category exists
    category = category_service.get_category_by_id(db=db, category_id=category_id)
    if not category:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Category not found"
        )
    
    # Check if category has products (prevent deletion of categories with products)
    if category.products:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Cannot delete category with existing products"
        )
    
    try:
        success = category_service.delete_category(db=db, category_id=category_id)
        if not success:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Category not found"
            )
        
        return {
            "success": True,
            "message": "Category deleted successfully",
            "data": None
        }
    except Exception:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to delete category"
        )
