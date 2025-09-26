from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session, joinedload
from uuid import UUID

from db.session import get_db
from core.auth import role_required, verify_password, hashpassword
from core.model import User, Profile
from schemas.profile import (
    ProfileUpdate, 
    PasswordChange, 
    ProfileUpdateResponse, 
    PasswordChangeResponse,
    UserResponse
)

router = APIRouter()


@router.get("/me", response_model=ProfileUpdateResponse)
async def get_my_profile(
    user=Depends(role_required(["customer", "seller", "admin"])),
    db: Session = Depends(get_db)
):
    """Get current user's profile"""
    
    user_obj = (
        db.query(User)
        .options(joinedload(User.profile))
        .filter(User.id == user["id"])
        .first()
    )
    
    if not user_obj:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User not found"
        )
    
    return ProfileUpdateResponse(
        success=True,
        message="Profile retrieved successfully",
        data=UserResponse.model_validate(user_obj)
    )


@router.put("/me", response_model=ProfileUpdateResponse)
async def update_my_profile(
    profile_data: ProfileUpdate,
    user=Depends(role_required(["customer", "seller", "admin"])),
    db: Session = Depends(get_db)
):
    """Update current user's profile"""
    
    # Get user with profile
    user_obj = (
        db.query(User)
        .options(joinedload(User.profile))
        .filter(User.id == user["id"])
        .first()
    )
    
    if not user_obj:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User not found"
        )
    
    # Update profile fields
    update_data = profile_data.model_dump(exclude_unset=True)
    for field, value in update_data.items():
        setattr(user_obj.profile, field, value)
    
    db.commit()
    db.refresh(user_obj)
    
    return ProfileUpdateResponse(
        success=True,
        message="Profile updated successfully",
        data=UserResponse.model_validate(user_obj)
    )


@router.post("/change-password", response_model=PasswordChangeResponse)
async def change_password(
    password_data: PasswordChange,
    user=Depends(role_required(["customer", "seller", "admin"])),
    db: Session = Depends(get_db)
):
    """Change user's password"""
    
    # Validate password confirmation
    if password_data.new_password != password_data.confirm_password:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="New password and confirmation do not match"
        )
    
    # Get user
    user_obj = db.query(User).filter(User.id == user["id"]).first()
    if not user_obj:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User not found"
        )
    
    # Verify current password
    if not verify_password(password_data.current_password, user_obj.password):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Current password is incorrect"
        )
    
    # Hash and update new password
    user_obj.password = hashpassword(password_data.new_password)
    db.commit()
    
    return PasswordChangeResponse(
        success=True,
        message="Password changed successfully"
    )


@router.delete("/me", status_code=status.HTTP_204_NO_CONTENT)
async def delete_my_account(
    user=Depends(role_required(["customer", "seller"])),
    db: Session = Depends(get_db)
):
    """Delete current user's account (customers and sellers only)"""
    
    user_obj = db.query(User).filter(User.id == user["id"]).first()
    if not user_obj:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User not found"
        )
    
    # Note: In a real application, you might want to:
    # 1. Cancel active orders
    # 2. Handle seller products
    # 3. Anonymize data instead of hard delete
    # 4. Send confirmation email
    
    db.delete(user_obj)
    db.commit()
    return None