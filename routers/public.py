from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from db.session import get_db
from core.automotive_service import automotive_service
from core.property_service import property_service
from core.model import DeliveryState
from core.system_settings_service import system_settings_service
from schemas.automotive import CarResponse
from schemas.property import PropertyResponse
from typing import List

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


@router.get("/delivery/states", response_model=dict)
def get_public_delivery_states(db: Session = Depends(get_db)):
    """Get all active delivery states for public use (dropdown)"""
    states = db.query(DeliveryState).filter(
        DeliveryState.is_active == True
    ).order_by(DeliveryState.state_name).all()

    return {
        "success": True,
        "message": "Delivery states fetched successfully",
        "data": [
            {
                "id": str(state.id),
                "state_name": state.state_name,
                "delivery_price": float(state.delivery_price) if state.delivery_price else None
            }
            for state in states
        ]
    }


@router.get("/delivery/settings", response_model=dict)
def get_public_delivery_settings(db: Session = Depends(get_db)):
    """Get public delivery settings (base price, pickup location)"""
    settings = system_settings_service.get_or_create_settings(db)

    return {
        "success": True,
        "message": "Delivery settings fetched successfully",
        "data": {
            "base_delivery_price": float(settings.base_delivery_price) if settings.base_delivery_price else 0,
            "store_pickup_location": settings.store_pickup_location,
            "store_pickup_address": settings.store_pickup_address
        }
    }


@router.get("/promo-banner", response_model=dict)
def get_public_promo_banner(db: Session = Depends(get_db)):
    """Get admin-configured storefront promo banner settings."""
    promo = system_settings_service.get_promo_setting_values(db)

    return {
        "success": True,
        "message": "Promo banner settings fetched successfully",
        "data": promo,
    }
