from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from typing import List, Optional
from uuid import UUID

from db.session import get_db
from core.auth import get_current_user, role_required
from core.property_service import property_service
from core.system_settings_service import system_settings_service
from schemas.property import (
    PropertyResponse, PropertyCreate, PropertyUpdate, 
    SessionRequestResponse, SessionRequestCreate
)

router = APIRouter(tags=["Properties"])

@router.get("/", response_model=dict)
def list_available_properties(db: Session = Depends(get_db)):
    properties = property_service.list_properties(db)
    return {
        "success": True,
        "message": "Properties fetched successfully",
        "data": [PropertyResponse.model_validate(p) for p in properties]
    }

@router.post("/")
def create_property(
    data: PropertyCreate, 
    db: Session = Depends(get_db), 
    current_user: dict = Depends(role_required(["seller", "admin"]))
):
    """Create a new property listing (Seller/Admin only)"""
    system_settings_service.require_verified_email_for_user(db, current_user["id"], "create a property listing")
    if current_user["role"] == "seller":
        system_settings_service.require_approved_seller_kyc(db, current_user["id"], "create a property listing")
    prop = property_service.create_property(db, UUID(current_user["id"]), data)
    return {
        "success": True,
        "message": "Property created successfully",
        "data": PropertyResponse.model_validate(prop)
    }

@router.get("/seller/listings", response_model=dict)
def list_seller_listings(
    db: Session = Depends(get_db),
    current_user: dict = Depends(role_required(["seller", "admin"]))
):
    properties = property_service.list_properties(db, seller_id=UUID(current_user["id"]), status=None)
    return {
        "success": True,
        "message": "Seller listings fetched successfully",
        "data": [PropertyResponse.model_validate(p) for p in properties]
    }

@router.post("/session-request", response_model=dict)
def create_session_request(
    data: SessionRequestCreate,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user)
):
    request = property_service.create_session_request(db, UUID(current_user["id"]), data)
    return {
        "success": True,
        "message": "Session request submitted successfully",
        "data": SessionRequestResponse.model_validate(request)
    }

@router.get("/session-requests", response_model=dict)
def get_my_session_requests(
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user)
):
    requests = property_service.list_session_requests(db, user_id=UUID(current_user["id"]))
    return {
        "success": True,
        "message": "Session requests fetched successfully",
        "data": [SessionRequestResponse.model_validate(r) for r in requests]
    }

@router.get("/session-requests/{id}", response_model=dict)
def get_session_request(
    id: UUID,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user)
):
    from core.model import RealEstateSessionRequest
    req = db.query(RealEstateSessionRequest).filter(RealEstateSessionRequest.id == id).first()
    if not req:
        raise HTTPException(status_code=404, detail="Session request not found")
        
    if str(req.user_id) != current_user["id"] and current_user["role"] != "admin":
        raise HTTPException(status_code=403, detail="Not authorized to view this request")
        
    return {
        "success": True,
        "message": "Session request detail fetched successfully",
        "data": SessionRequestResponse.model_validate(req)
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
    current_user: dict = Depends(role_required(["seller", "admin"]))
):
    """Update a property listing"""
    system_settings_service.require_verified_email_for_user(db, current_user["id"], "update a property listing")
    if current_user["role"] == "seller":
        system_settings_service.require_approved_seller_kyc(db, current_user["id"], "update a property listing")
    prop = property_service.update_property(db, id, UUID(current_user["id"]), data)
    return {
        "success": True,
        "message": "Property updated successfully",
        "data": PropertyResponse.model_validate(prop)
    }

@router.delete("/{id}", response_model=dict)
def delete_property(
    id: UUID,
    db: Session = Depends(get_db),
    current_user: dict = Depends(role_required(["seller", "admin"]))
):
    """Delete a property listing"""
    from core.model import Property, AssetImage
    
    # Check ownership
    prop = db.query(Property).filter(Property.id == id).first()
    if not prop:
        raise HTTPException(status_code=404, detail="Property not found")
        
    if str(prop.seller_id) != current_user["id"] and current_user["role"] != "admin":
        raise HTTPException(status_code=403, detail="Not authorized to delete this property")
        
    db.query(AssetImage).filter(AssetImage.property_id == id).delete()
    db.delete(prop)
    db.commit()
    
    return {
        "success": True,
        "message": "Property deleted successfully",
        "data": None
    }
