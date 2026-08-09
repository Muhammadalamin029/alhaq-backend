from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from db.session import get_db
from core.automotive_service import automotive_service
from core.property_service import property_service
from schemas.automotive import CarResponse
from schemas.property import PropertyResponse

router = APIRouter(tags=["Public"])

@router.get("/automotive/featured", response_model=dict)
def get_public_featured_cars(db: Session = Depends(get_db)):
    """Get featured/available cars"""
    cars = automotive_service.list_cars(db, status="available", max_price=None, min_price=None, seller_id=None)
    # limit to top 10 for featured
    cars = cars[:10]
    return {
        "success": True,
        "message": "Featured cars fetched successfully",
        "data": [CarResponse.model_validate(c).model_dump() for c in cars]
    }

@router.get("/properties/featured", response_model=dict)
def get_public_featured_properties(db: Session = Depends(get_db)):
    """Get featured/available properties"""
    properties = property_service.list_properties(db, status="available")
    # limit to top 10 for featured
    properties = properties[:10]
    return {
        "success": True,
        "message": "Featured properties fetched successfully",
        "data": [PropertyResponse.model_validate(p).model_dump() for p in properties]
    }
