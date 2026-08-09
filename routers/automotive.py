from fastapi import APIRouter, Depends, HTTPException, status, Query
from sqlalchemy.orm import Session
from typing import List, Optional
from uuid import UUID

from db.session import get_db
from core.auth import role_required
from core.automotive_service import automotive_service
from core.system_settings_service import system_settings_service
from core.store_service import get_store_id
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
    current_user: dict = Depends(role_required(["admin"]))
):
    """Update a physical car unit (Admin only)"""
    system_settings_service.require_verified_email_for_user(db, current_user["id"], "update a car unit")

    unit = automotive_service.update_car_unit(db, unit_id, get_store_id(db), body)
    return {
        "success": True,
        "message": "Car unit updated successfully",
        "data": CarUnitResponse.model_validate(unit)
    }


@router.delete("/units/{unit_id}")
def delete_car_unit(
    unit_id: UUID,
    db: Session = Depends(get_db),
    current_user: dict = Depends(role_required(["admin"]))
):
    """Delete a physical car unit (Admin only)"""
    automotive_service.delete_car_unit(db, unit_id, get_store_id(db))
    return {
        "success": True,
        "message": "Car unit deleted successfully"
    }

@router.delete("/{car_id}")
def delete_car_listing(
    car_id: UUID,
    db: Session = Depends(get_db),
    current_user: dict = Depends(role_required(["admin"]))
):
    """Delete a car listing (Admin only)"""
    automotive_service.delete_car(db, car_id, get_store_id(db))
    return {
        "success": True,
        "message": "Car listing deleted successfully"
    }

@router.post("/", status_code=status.HTTP_201_CREATED)
def create_car_listing(
    body: CarCreate,
    db: Session = Depends(get_db),
    current_user: dict = Depends(role_required(["admin"]))
):
    """List a new car (Admin only)"""
    system_settings_service.require_verified_email_for_user(db, current_user["id"], "create a car listing")

    car = automotive_service.create_car(db, get_store_id(db), body)
    return {
        "success": True,
        "message": "Car listing created successfully",
        "data": CarResponse.model_validate(car)
    }

@router.get("/seller/listings")
def get_seller_cars(
    db: Session = Depends(get_db),
    current_user: dict = Depends(role_required(["admin"]))
):
    """Get cars listed by the store (Admin only)"""
    cars = automotive_service.list_cars(db, seller_id=get_store_id(db))
    return {
        "success": True,
        "message": "Store listings fetched successfully",
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
    current_user: dict = Depends(role_required(["admin"]))
):
    """Update car listing (Admin only)"""
    system_settings_service.require_verified_email_for_user(db, current_user["id"], "update a car listing")
    car = automotive_service.update_car(db, car_id, get_store_id(db), body)
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
    current_user: dict = Depends(role_required(["admin"]))
):
    """Add more physical units to an existing car listing (Admin only)"""
    system_settings_service.require_verified_email_for_user(db, current_user["id"], "add car units")
    new_units = automotive_service.add_units_to_listing(db, car_id, get_store_id(db), units)
    return {
        "success": True,
        "message": "Units added successfully",
        "data": [CarUnitResponse.model_validate(u) for u in new_units]
    }
