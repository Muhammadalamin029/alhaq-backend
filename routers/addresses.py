from fastapi import APIRouter, Depends, HTTPException, status, Query
from sqlalchemy.orm import Session
from typing import List
from uuid import UUID

from db.session import get_db
from core.auth import role_required
from core.model import Address
from schemas.address import (
    AddressCreate, 
    AddressUpdate, 
    AddressResponse, 
    AddressListResponse, 
    AddressSingleResponse
)

router = APIRouter()


@router.get("/", response_model=AddressListResponse)
async def list_addresses(
    user=Depends(role_required(["customer", "seller", "admin"])),
    db: Session = Depends(get_db),
    page: int = Query(1, ge=1),
    limit: int = Query(50, ge=1, le=100)
):
    """Get all addresses for the current user"""
    q = db.query(Address).filter(Address.user_id == user["id"]) 
    total = q.count()
    addresses = q.order_by(Address.created_at.desc()).offset((page - 1) * limit).limit(limit).all()
    
    return AddressListResponse(
        success=True,
        message="Addresses retrieved successfully",
        data=[AddressResponse.model_validate(addr) for addr in addresses],
        pagination={
            "page": page,
            "limit": limit,
            "total": total,
            "total_pages": (total + limit - 1) // limit
        }
    )


@router.post("/", response_model=AddressSingleResponse, status_code=status.HTTP_201_CREATED)
async def create_address(
    address_data: AddressCreate,
    user=Depends(role_required(["customer", "seller", "admin"])),
    db: Session = Depends(get_db)
):
    """Create a new address for the current user"""
    
    # If this is set as default, unset all other default addresses
    if address_data.is_default:
        db.query(Address).filter(
            Address.user_id == user["id"],
            Address.is_default == True
        ).update({"is_default": False})
    
    # If this is the first address, make it default
    existing_count = db.query(Address).filter(Address.user_id == user["id"]).count()
    if existing_count == 0:
        address_data.is_default = True
    
    new_address = Address(
        user_id=user["id"],
        **address_data.model_dump()
    )
    
    db.add(new_address)
    db.commit()
    db.refresh(new_address)
    
    return AddressSingleResponse(
        success=True,
        message="Address created successfully",
        data=AddressResponse.model_validate(new_address)
    )


@router.get("/{address_id}", response_model=AddressSingleResponse)
async def get_address(
    address_id: UUID,
    user=Depends(role_required(["customer", "seller", "admin"])),
    db: Session = Depends(get_db)
):
    """Get a specific address by ID"""
    address = db.query(Address).filter(
        Address.id == address_id,
        Address.user_id == user["id"]
    ).first()
    
    if not address:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Address not found"
        )
    
    return AddressSingleResponse(
        success=True,
        message="Address retrieved successfully",
        data=AddressResponse.model_validate(address)
    )


@router.put("/{address_id}", response_model=AddressSingleResponse)
async def update_address(
    address_id: UUID,
    address_data: AddressUpdate,
    user=Depends(role_required(["customer", "seller", "admin"])),
    db: Session = Depends(get_db)
):
    """Update an existing address"""
    address = db.query(Address).filter(
        Address.id == address_id,
        Address.user_id == user["id"]
    ).first()
    
    if not address:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Address not found"
        )
    
    # If setting as default, unset all other default addresses
    if address_data.is_default:
        db.query(Address).filter(
            Address.user_id == user["id"],
            Address.is_default == True,
            Address.id != address_id
        ).update({"is_default": False})
    
    # Update address fields
    update_data = address_data.model_dump(exclude_unset=True)
    for field, value in update_data.items():
        setattr(address, field, value)
    
    db.commit()
    db.refresh(address)
    
    return AddressSingleResponse(
        success=True,
        message="Address updated successfully",
        data=AddressResponse.model_validate(address)
    )


@router.delete("/{address_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_address(
    address_id: UUID,
    user=Depends(role_required(["customer", "seller", "admin"])),
    db: Session = Depends(get_db)
):
    """Delete an address"""
    address = db.query(Address).filter(
        Address.id == address_id,
        Address.user_id == user["id"]
    ).first()
    
    if not address:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Address not found"
        )
    
    was_default = address.is_default
    db.delete(address)
    
    # If deleted address was default, make another address default
    if was_default:
        next_address = db.query(Address).filter(Address.user_id == user["id"]).first()
        if next_address:
            next_address.is_default = True
    
    db.commit()
    return None


@router.post("/{address_id}/set-default", response_model=AddressSingleResponse)
async def set_default_address(
    address_id: UUID,
    user=Depends(role_required(["customer", "seller", "admin"])),
    db: Session = Depends(get_db)
):
    """Set an address as the default address"""
    address = db.query(Address).filter(
        Address.id == address_id,
        Address.user_id == user["id"]
    ).first()
    
    if not address:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Address not found"
        )
    
    # Unset all other default addresses
    db.query(Address).filter(
        Address.user_id == user["id"],
        Address.is_default == True
    ).update({"is_default": False})
    
    # Set this address as default
    address.is_default = True
    db.commit()
    db.refresh(address)
    
    return AddressSingleResponse(
        success=True,
        message="Default address updated successfully",
        data=AddressResponse.model_validate(address)
    )
