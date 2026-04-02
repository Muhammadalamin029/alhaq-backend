from fastapi import APIRouter, Depends, HTTPException, status, Query
from sqlalchemy.orm import Session
from typing import List, Optional
from uuid import UUID

from db.session import get_db
from core.auth import get_current_user
from core.automotive_service import automotive_service
from core.system_settings_service import system_settings_service
from schemas.automotive import (
    CarCreate, 
    CarUpdate, 
    CarResponse, 
    CarUnitCreate, 
    CarUnitResponse, 
    CarUnitUpdate
)
from core.model import User

router = APIRouter()

@router.put("/units/{unit_id}")
def update_car_unit(
    unit_id: UUID,
    body: CarUnitUpdate,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user)
):
    """Update a physical car unit (Seller only)"""
    if current_user["role"] not in ["seller", "admin"]:
        raise HTTPException(status_code=403, detail="Only sellers can update units")
    system_settings_service.require_verified_email_for_user(db, current_user["id"], "update a car unit")
    if current_user["role"] == "seller":
        system_settings_service.require_approved_seller_kyc(db, current_user["id"], "update a car unit")
    
    unit = automotive_service.update_car_unit(db, unit_id, UUID(current_user["id"]), body)
    return {
        "success": True,
        "message": "Car unit updated successfully",
        "data": CarUnitResponse.model_validate(unit)
    }


@router.delete("/units/{unit_id}")
def delete_car_unit(
    unit_id: UUID,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user)
):
    """Delete a physical car unit (Seller only)"""
    if current_user["role"] not in ["seller", "admin"]:
        raise HTTPException(status_code=403, detail="Only sellers can delete units")
    
    automotive_service.delete_car_unit(db, unit_id, UUID(current_user["id"]))
    return {
        "success": True,
        "message": "Car unit deleted successfully"
    }

@router.delete("/{car_id}")
def delete_car_listing(
    car_id: UUID,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user)
):
    """Delete a car listing (Seller only)"""
    if current_user["role"] not in ["seller", "admin"]:
        raise HTTPException(status_code=403, detail="Only sellers can delete listings")
    
    automotive_service.delete_car(db, car_id, UUID(current_user["id"]))
    return {
        "success": True,
        "message": "Car listing deleted successfully"
    }

@router.post("/", status_code=status.HTTP_201_CREATED)
def create_car_listing(
    body: CarCreate, 
    db: Session = Depends(get_db), 
    current_user: dict = Depends(get_current_user)
):
    """List a new car (Sellers only)"""
    if current_user["role"] not in ["seller", "admin"]:
        raise HTTPException(status_code=403, detail="Only sellers can list cars")
    system_settings_service.require_verified_email_for_user(db, current_user["id"], "create a car listing")
    if current_user["role"] == "seller":
        system_settings_service.require_approved_seller_kyc(db, current_user["id"], "create a car listing")
    
    car = automotive_service.create_car(db, UUID(current_user["id"]), body)
    return {
        "success": True,
        "message": "Car listing created successfully",
        "data": CarResponse.model_validate(car)
    }

@router.get("/seller/listings")
def get_seller_cars(
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user)
):
    """Get cars listed by the current seller"""
    if current_user["role"] not in ["seller", "admin"]:
        raise HTTPException(status_code=403, detail="Only sellers can view their listings")
    cars = automotive_service.list_cars(db, seller_id=UUID(current_user["id"]))
    return {
        "success": True,
        "message": "Seller listings fetched successfully",
        "data": [CarResponse.model_validate(c) for c in cars]
    }

@router.get("/")
def get_cars(
    brand: Optional[str] = None,
    model: Optional[str] = None,
    status: Optional[str] = "available",
    min_price: Optional[float] = None,
    max_price: Optional[float] = None,
    seller_id: Optional[UUID] = None,
    db: Session = Depends(get_db)
):
    """Get all cars with filters"""
    cars = automotive_service.list_cars(db, brand, model, status, min_price, max_price, seller_id)
    return {
        "success": True,
        "message": "Cars fetched successfully",
        "data": [CarResponse.model_validate(c) for c in cars]
    }

@router.get("/{car_id}")
def get_car_details(car_id: UUID, db: Session = Depends(get_db)):
    """Get car details by ID"""
    car = automotive_service.get_car(db, car_id)
    if not car:
        raise HTTPException(status_code=404, detail="Car not found")
    return {
        "success": True,
        "message": "Car details fetched successfully",
        "data": CarResponse.model_validate(car)
    }

@router.put("/{car_id}")
def update_car_listing(
    car_id: UUID, 
    body: CarUpdate, 
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user)
):
    """Update car listing (Seller only)"""
    system_settings_service.require_verified_email_for_user(db, current_user["id"], "update a car listing")
    if current_user["role"] == "seller":
        system_settings_service.require_approved_seller_kyc(db, current_user["id"], "update a car listing")
    car = automotive_service.update_car(db, car_id, UUID(current_user["id"]), body)
    return {
        "success": True,
        "message": "Car listing updated successfully",
        "data": CarResponse.model_validate(car)
    }


@router.post("/{car_id}/units")
def add_car_units(
    car_id: UUID,
    units: List[CarUnitCreate],
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user)
):
    """Add more physical units to an existing car listing (Seller only)"""
    if current_user["role"] not in ["seller", "admin"]:
        raise HTTPException(status_code=403, detail="Only sellers can add units")
    system_settings_service.require_verified_email_for_user(db, current_user["id"], "add car units")
    if current_user["role"] == "seller":
        system_settings_service.require_approved_seller_kyc(db, current_user["id"], "add car units")
    new_units = automotive_service.add_units_to_listing(db, car_id, UUID(current_user["id"]), units)
    return {
        "success": True,
        "message": "Units added successfully",
        "data": [CarUnitResponse.model_validate(u) for u in new_units]
    }

