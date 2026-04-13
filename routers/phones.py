from fastapi import APIRouter, Depends, HTTPException, status, Query
from sqlalchemy.orm import Session
from typing import List, Optional
from uuid import UUID

from db.session import get_db
from core.auth import get_current_user
from core.phone_service import phone_service
from core.system_settings_service import system_settings_service
from schemas.phone import (
    PhoneCreate, 
    PhoneUpdate, 
    PhoneResponse, 
    PhoneUnitCreate,
    PhoneUnitUpdate,
    PhoneUnitResponse
)
from core.model import Phone, PhoneUnit, AssetImage

router = APIRouter()

@router.delete("/units/{unit_id}")
def delete_phone_unit(
    unit_id: UUID,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user)
):
    """Delete a physical phone unit (Seller only)"""
    if current_user["role"] not in ["seller", "admin"]:
        raise HTTPException(status_code=403, detail="Only sellers can delete units")
    
    unit = db.query(PhoneUnit).join(Phone).filter(
        PhoneUnit.id == unit_id, 
        Phone.seller_id == UUID(current_user["id"])
    ).first()
    
    if not unit:
        raise HTTPException(status_code=404, detail="Phone unit not found or unauthorized")
        
    db.delete(unit)
    db.commit()
    return {
        "success": True,
        "message": "Phone unit deleted successfully"
    }

@router.put("/units/{unit_id}")
def update_phone_unit(
    unit_id: UUID,
    body: PhoneUnitUpdate,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user)
):
    """Update a physical phone unit (Seller only)"""
    if current_user["role"] not in ["seller", "admin"]:
        raise HTTPException(status_code=403, detail="Only sellers can update units")
    
    unit = phone_service.update_phone_unit(db, unit_id, UUID(current_user["id"]), body)
    return {
        "success": True,
        "message": "Phone unit updated successfully",
        "data": PhoneUnitResponse.model_validate(unit)
    }

@router.delete("/{phone_id}")
def delete_phone_listing(
    phone_id: UUID,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user)
):
    """Delete a phone listing (Seller only)"""
    if current_user["role"] not in ["seller", "admin"]:
        raise HTTPException(status_code=403, detail="Only sellers can delete listings")
    
    phone = db.query(Phone).filter(
        Phone.id == phone_id, 
        Phone.seller_id == UUID(current_user["id"])
    ).first()
    
    if not phone:
        raise HTTPException(status_code=404, detail="Phone listing not found or unauthorized")
        
    db.delete(phone)
    db.commit()
    return {
        "success": True,
        "message": "Phone listing deleted successfully"
    }

@router.post("/", status_code=status.HTTP_201_CREATED)
def create_phone_listing(
    body: PhoneCreate, 
    db: Session = Depends(get_db), 
    current_user: dict = Depends(get_current_user)
):
    """List a new phone (Sellers only)"""
    if current_user["role"] not in ["seller", "admin"]:
        raise HTTPException(status_code=403, detail="Only sellers can list phones")
    system_settings_service.require_verified_email_for_user(db, current_user["id"], "create a phone listing")
    if current_user["role"] == "seller":
        system_settings_service.require_approved_seller_kyc(db, current_user["id"], "create a phone listing")
    
    phone = phone_service.create_phone(db, UUID(current_user["id"]), body)
    return {
        "success": True,
        "message": "Phone listing created successfully",
        "data": PhoneResponse.model_validate(phone)
    }

@router.get("/seller/listings")
def get_seller_phones(
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user)
):
    """Get phones listed by the current seller"""
    if current_user["role"] not in ["seller", "admin"]:
        raise HTTPException(status_code=403, detail="Only sellers can view their listings")
    phones = phone_service.list_phones(db, seller_id=UUID(current_user["id"]))
    return {
        "success": True,
        "message": "Seller listings fetched successfully",
        "data": [PhoneResponse.model_validate(p) for p in phones]
    }

@router.get("/")
def get_phones(
    db: Session = Depends(get_db)
):
    """Get all phones with filters"""
    phones = phone_service.list_phones(db, None)
    return {
        "success": True,
        "message": "Phones fetched successfully",
        "data": [PhoneResponse.model_validate(p) for p in phones]
    }

@router.get("/{phone_id}")
def get_phone_details(phone_id: UUID, db: Session = Depends(get_db)):
    """Get phone details by ID"""
    phone = phone_service.get_phone(db, phone_id)
    if not phone:
        raise HTTPException(status_code=404, detail="Phone not found")
    return {
        "success": True,
        "message": "Phone details fetched successfully",
        "data": PhoneResponse.model_validate(phone)
    }

@router.put("/{phone_id}")
def update_phone_listing(
    phone_id: UUID, 
    body: PhoneUpdate, 
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user)
):
    """Update phone listing (Seller only)"""
    system_settings_service.require_verified_email_for_user(db, current_user["id"], "update a phone listing")
    if current_user["role"] == "seller":
        system_settings_service.require_approved_seller_kyc(db, current_user["id"], "update a phone listing")
    phone = phone_service.update_phone(db, phone_id, UUID(current_user["id"]), body)
    return {
        "success": True,
        "message": "Phone listing updated successfully",
        "data": PhoneResponse.model_validate(phone)
    }

@router.post("/{phone_id}/units")
def add_phone_units(
    phone_id: UUID,
    units: List[PhoneUnitCreate],
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user)
):
    """Add more physical units to an existing phone listing (Seller only)"""
    if current_user["role"] not in ["seller", "admin"]:
        raise HTTPException(status_code=403, detail="Only sellers can add units")
    system_settings_service.require_verified_email_for_user(db, current_user["id"], "add phone units")
    if current_user["role"] == "seller":
        system_settings_service.require_approved_seller_kyc(db, current_user["id"], "add phone units")
    new_units = phone_service.add_units_to_listing(db, phone_id, UUID(current_user["id"]), units)
    return {
        "success": True,
        "message": "Units added successfully",
        "data": [PhoneUnitResponse.model_validate(u) for u in new_units]
    }
