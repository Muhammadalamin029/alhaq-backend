from fastapi import APIRouter, Depends, HTTPException, status, Query
from sqlalchemy.orm import Session
from typing import List, Optional
from uuid import UUID

from db.session import get_db
from core.auth import get_current_user
from core.automotive_service import automotive_service
from schemas.automotive import (
    CarCreate, CarUpdate, CarResponse, CarInspectionResponse, 
    CarInspectionSchedule, CarInspectionComplete, CarUnitCreate, CarUnitResponse
)
from core.model import User

router = APIRouter()

@router.post("/", status_code=status.HTTP_201_CREATED)
def create_car_listing(
    body: CarCreate, 
    db: Session = Depends(get_db), 
    current_user: dict = Depends(get_current_user)
):
    """List a new car (Sellers only)"""
    if current_user["role"] not in ["seller", "admin"]:
        raise HTTPException(status_code=403, detail="Only sellers can list cars")
    
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

@router.get("/seller/inspections")
def get_seller_inspections(
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user)
):
    """Get inspections for cars listed by the current seller"""
    if current_user["role"] not in ["seller", "admin"]:
        raise HTTPException(status_code=403, detail="Only sellers can view their inspections")
    inspections = automotive_service.list_seller_inspections(db, seller_id=UUID(current_user["id"]))
    return {
        "success": True,
        "message": "Seller inspections fetched successfully",
        "data": [CarInspectionResponse.model_validate(i) for i in inspections]
    }

@router.get("/my-inspections")
def get_my_inspections(
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user)
):
    """Get inspections requested by the current customer"""
    inspections = automotive_service.list_user_inspections(db, user_id=UUID(current_user["id"]))
    return {
        "success": True,
        "message": "My inspections fetched successfully",
        "data": [CarInspectionResponse.model_validate(i) for i in inspections]
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
    car = automotive_service.update_car(db, car_id, UUID(current_user["id"]), body)
    return {
        "success": True,
        "message": "Car listing updated successfully",
        "data": CarResponse.model_validate(car)
    }

@router.post("/{car_id}/schedule-inspection")
def schedule_car_inspection(
    car_id: UUID,
    body: CarInspectionSchedule,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user)
):
    """Schedule a car inspection for a specific unit or listing (Customer)"""
    inspection = automotive_service.schedule_inspection(
        db, 
        UUID(current_user["id"]), 
        car_id, 
        body.inspection_date, 
        body.unit_id
    )
    return {
        "success": True,
        "message": "Inspection scheduled successfully",
        "data": CarInspectionResponse.model_validate(inspection)
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
    new_units = automotive_service.add_units_to_listing(db, car_id, UUID(current_user["id"]), units)
    return {
        "success": True,
        "message": "Units added successfully",
        "data": [CarUnitResponse.model_validate(u) for u in new_units]
    }

@router.post("/inspections/{inspection_id}/complete")
def complete_car_inspection(
    inspection_id: UUID,
    body: CarInspectionComplete,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user)
):
    """Mark car as inspected and propose price (Customer)"""
    inspection = automotive_service.complete_inspection(db, UUID(current_user["id"]), inspection_id, body.notes, body.agreed_price)
    return {
        "success": True,
        "message": "Inspection completed successfully",
        "data": CarInspectionResponse.model_validate(inspection)
    }

@router.post("/inspections/{inspection_id}/seller-action")
def seller_inspection_action(
    inspection_id: UUID,
    action: str = Query(..., regex="^(accept|reject)$"),
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user)
):
    """Accept or Reject the negotiated price (Seller)"""
    result = automotive_service.seller_action_on_inspection(db, UUID(current_user["id"]), inspection_id, action)
    return {
        "success": True,
        "message": f"Inspection {action}ed successfully",
        "data": CarInspectionResponse.model_validate(result)
    }
