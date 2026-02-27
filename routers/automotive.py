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

@router.post("/", response_model=CarResponse, status_code=status.HTTP_201_CREATED)
def create_car_listing(
    body: CarCreate, 
    db: Session = Depends(get_db), 
    current_user: dict = Depends(get_current_user)
):
    """List a new car (Sellers only)"""
    if current_user["role"] not in ["seller", "admin"]:
        raise HTTPException(status_code=403, detail="Only sellers can list cars")
    
    return automotive_service.create_car(db, UUID(current_user["id"]), body)

@router.get("/", response_model=List[CarResponse])
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
    return automotive_service.list_cars(db, brand, model, status, min_price, max_price, seller_id)

@router.get("/{car_id}", response_model=CarResponse)
def get_car_details(car_id: UUID, db: Session = Depends(get_db)):
    """Get car details by ID"""
    car = automotive_service.get_car(db, car_id)
    if not car:
        raise HTTPException(status_code=404, detail="Car not found")
    return car

@router.put("/{car_id}", response_model=CarResponse)
def update_car_listing(
    car_id: UUID, 
    body: CarUpdate, 
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user)
):
    """Update car listing (Seller only)"""
    return automotive_service.update_car(db, car_id, UUID(current_user["id"]), body)

@router.post("/{car_id}/schedule-inspection", response_model=CarInspectionResponse)
def schedule_car_inspection(
    car_id: UUID,
    body: CarInspectionSchedule,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user)
):
    """Schedule a car inspection for a specific unit or listing (Customer)"""
    return automotive_service.schedule_inspection(
        db, 
        UUID(current_user["id"]), 
        car_id, 
        body.inspection_date, 
        body.unit_id
    )

@router.post("/{car_id}/units", response_model=List[CarUnitResponse])
def add_car_units(
    car_id: UUID,
    units: List[CarUnitCreate],
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user)
):
    """Add more physical units to an existing car listing (Seller only)"""
    if current_user["role"] not in ["seller", "admin"]:
        raise HTTPException(status_code=403, detail="Only sellers can add units")
    return automotive_service.add_units_to_listing(db, car_id, UUID(current_user["id"]), units)

@router.post("/inspections/{inspection_id}/complete", response_model=CarInspectionResponse)
def complete_car_inspection(
    inspection_id: UUID,
    body: CarInspectionComplete,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user)
):
    """Mark car as inspected and propose price (Customer)"""
    return automotive_service.complete_inspection(db, UUID(current_user["id"]), inspection_id, body.notes, body.agreed_price)

@router.post("/inspections/{inspection_id}/seller-action")
def seller_inspection_action(
    inspection_id: UUID,
    action: str = Query(..., regex="^(accept|reject)$"),
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user)
):
    """Accept or Reject the negotiated price (Seller)"""
    return automotive_service.seller_action_on_inspection(db, UUID(current_user["id"]), inspection_id, action)
