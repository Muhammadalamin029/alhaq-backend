from fastapi import APIRouter, Depends, HTTPException, status, Query
from sqlalchemy.orm import Session
from typing import List, Optional
from uuid import UUID

from db.session import get_db
from core.auth import role_required
from core.property_service import property_service
from core.system_settings_service import system_settings_service
from core.store_service import get_store_id
from schemas.property import (
    PropertyResponse, PropertyCreate, PropertyUpdate,
)

router = APIRouter(tags=["Properties"])

@router.get("/", response_model=dict)
def list_available_properties(
    db: Session = Depends(get_db),
    search: Optional[str] = Query(None, description="Search by title or location"),
):
    properties = property_service.list_properties(db, search=search)
    return {
        "success": True,
        "message": "Properties fetched successfully",
        "data": [PropertyResponse.model_validate(p) for p in properties]
    }

@router.post("/")
def create_property(
    data: PropertyCreate,
    db: Session = Depends(get_db),
    current_user: dict = Depends(role_required(["admin"]))
):
    """Create a new property listing (Admin only)"""
    system_settings_service.require_verified_email_for_user(db, current_user["id"], "create a property listing")
    prop = property_service.create_property(db, get_store_id(db), data)
    return {
        "success": True,
        "message": "Property created successfully",
        "data": PropertyResponse.model_validate(prop)
    }

@router.get("/seller/listings", response_model=dict)
def list_seller_listings(
    db: Session = Depends(get_db),
    current_user: dict = Depends(role_required(["admin"]))
):
    properties = property_service.list_properties(db, seller_id=get_store_id(db), status=None)
    return {
        "success": True,
        "message": "Store listings fetched successfully",
        "data": [PropertyResponse.model_validate(p) for p in properties]
    }

@router.get("/{id}", response_model=dict)
def get_property(id: UUID, db: Session = Depends(get_db)):
    prop = property_service.get_property(db, id)
    if not prop:
        raise HTTPException(status_code=404, detail="Property not found")
    return {
        "success": True,
        "message": "Property details fetched successfully",
        "data": PropertyResponse.model_validate(prop)
    }

@router.put("/{id}", response_model=dict)
def update_property(
    id: UUID,
    data: PropertyUpdate,
    db: Session = Depends(get_db),
    current_user: dict = Depends(role_required(["admin"]))
):
    """Update a property listing (Admin only)"""
    system_settings_service.require_verified_email_for_user(db, current_user["id"], "update a property listing")
    prop = property_service.update_property(db, id, get_store_id(db), data)
    return {
        "success": True,
        "message": "Property updated successfully",
        "data": PropertyResponse.model_validate(prop)
    }

@router.delete("/{id}", response_model=dict)
def delete_property(
    id: UUID,
    db: Session = Depends(get_db),
    current_user: dict = Depends(role_required(["admin"]))
):
    """Delete a property listing (Admin only)"""
    from core.model import Property, AssetImage

    prop = db.query(Property).filter(Property.id == id).first()
    if not prop:
        raise HTTPException(status_code=404, detail="Property not found")

    db.query(AssetImage).filter(AssetImage.property_id == id).delete()
    db.delete(prop)
    db.commit()

    return {
        "success": True,
        "message": "Property deleted successfully",
        "data": None
    }
