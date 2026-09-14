from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from typing import List
import logging

from db.session import get_db
from core.auth import role_required
from core.model import DeliveryState, SystemSettings
from core.system_settings_service import system_settings_service
from schemas.delivery import (
    DeliveryStateCreate,
    DeliveryStateUpdate,
    DeliveryStateResponse,
    DeliverySettingsUpdate,
    DeliverySettingsResponse
)

logger = logging.getLogger(__name__)

router = APIRouter()


@router.get("/settings", response_model=DeliverySettingsResponse)
async def get_delivery_settings(
    user=Depends(role_required(["admin"])),
    db: Session = Depends(get_db)
):
    """Get current delivery settings"""
    settings = system_settings_service.get_or_create_settings(db)
    return DeliverySettingsResponse(
        base_delivery_price=settings.base_delivery_price or 0,
        store_pickup_location=settings.store_pickup_location,
        store_pickup_address=settings.store_pickup_address
    )


@router.put("/settings", response_model=DeliverySettingsResponse)
async def update_delivery_settings(
    settings_update: DeliverySettingsUpdate,
    user=Depends(role_required(["admin"])),
    db: Session = Depends(get_db)
):
    """Update delivery settings"""
    settings = system_settings_service.get_or_create_settings(db)
    
    if settings_update.base_delivery_price is not None:
        settings.base_delivery_price = settings_update.base_delivery_price
    if settings_update.store_pickup_location is not None:
        settings.store_pickup_location = settings_update.store_pickup_location
    if settings_update.store_pickup_address is not None:
        settings.store_pickup_address = settings_update.store_pickup_address
    
    db.commit()
    db.refresh(settings)
    
    return DeliverySettingsResponse(
        base_delivery_price=settings.base_delivery_price or 0,
        store_pickup_location=settings.store_pickup_location,
        store_pickup_address=settings.store_pickup_address
    )


@router.get("/states", response_model=List[DeliveryStateResponse])
async def get_delivery_states(
    user=Depends(role_required(["admin"])),
    db: Session = Depends(get_db)
):
    """Get all delivery states with their prices"""
    states = db.query(DeliveryState).order_by(DeliveryState.state_name).all()
    return states


@router.get("/states/{state_id}", response_model=DeliveryStateResponse)
async def get_delivery_state(
    state_id: str,
    user=Depends(role_required(["admin"])),
    db: Session = Depends(get_db)
):
    """Get a specific delivery state"""
    state = db.query(DeliveryState).filter(DeliveryState.id == state_id).first()
    if not state:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Delivery state not found"
        )
    return state


@router.put("/states/{state_id}", response_model=DeliveryStateResponse)
async def update_delivery_state(
    state_id: str,
    state_update: DeliveryStateUpdate,
    user=Depends(role_required(["admin"])),
    db: Session = Depends(get_db)
):
    """Update a delivery state's price or active status"""
    state = db.query(DeliveryState).filter(DeliveryState.id == state_id).first()
    if not state:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Delivery state not found"
        )
    
    if state_update.state_name is not None:
        state.state_name = state_update.state_name
    if state_update.delivery_price is not None:
        state.delivery_price = state_update.delivery_price
    if state_update.is_active is not None:
        state.is_active = state_update.is_active
    
    db.commit()
    db.refresh(state)
    
    return state


@router.post("/states", response_model=DeliveryStateResponse, status_code=status.HTTP_201_CREATED)
async def create_delivery_state(
    state_create: DeliveryStateCreate,
    user=Depends(role_required(["admin"])),
    db: Session = Depends(get_db)
):
    """Create a new delivery state"""
    # Check if state already exists
    existing = db.query(DeliveryState).filter(
        DeliveryState.state_name == state_create.state_name
    ).first()
    if existing:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="State with this name already exists"
        )
    
    new_state = DeliveryState(**state_create.model_dump())
    db.add(new_state)
    db.commit()
    db.refresh(new_state)
    
    return new_state


@router.delete("/states/{state_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_delivery_state(
    state_id: str,
    user=Depends(role_required(["admin"])),
    db: Session = Depends(get_db)
):
    """Deactivate a delivery state (soft delete)"""
    state = db.query(DeliveryState).filter(DeliveryState.id == state_id).first()
    if not state:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Delivery state not found"
        )
    
    state.is_active = False
    db.commit()
    
    return None
