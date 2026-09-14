from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session, joinedload
from decimal import Decimal
from datetime import datetime, timedelta
from uuid import UUID
import logging

from db.session import get_db
from core.auth import role_required
from core.model import Order, OrderItem, Address, DeliveryState
from core.order import order_service

logger = logging.getLogger(__name__)
from schemas.checkout import (
    CheckoutRequest, 
    CheckoutSummary, 
    CheckoutResponse,
    OrderConfirmation,
    OrderConfirmationResponse
)
from schemas.order import OrderResponse
from core.notifications_service import create_notification
from core.system_settings_service import system_settings_service

router = APIRouter()


@router.get("/summary", response_model=CheckoutResponse)
async def get_checkout_summary(
    user=Depends(role_required(["customer"])),
    db: Session = Depends(get_db)
):
    """Get checkout summary for pending order"""

    # Get pending order
    pending_order = order_service.get_orders_by_status(
        db=db, user_id=user["id"], status="pending"
    )

    if not pending_order:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No pending order found"
        )

    # Calculate totals
    subtotal = Decimal(str(pending_order.total_amount))
    # Delivery fee will be calculated based on delivery type and address
    # Default to 0 for now, will be updated during checkout process
    shipping_fee = Decimal("0.00")
    delivery_fee = Decimal("0.00")
    tax = Decimal("0.00")  # No tax for now
    total = subtotal + shipping_fee + delivery_fee + tax

    items_count = len(pending_order.order_items)

    summary = CheckoutSummary(
        subtotal=subtotal,
        shipping_fee=shipping_fee,
        delivery_fee=delivery_fee,
        tax=tax,
        total=total,
        items_count=items_count
    )

    return CheckoutResponse(
        success=True,
        message="Checkout summary retrieved successfully",
        data={
            "order": OrderResponse.model_validate(pending_order).model_dump(by_alias=True),
            "summary": summary.model_dump()
        }
    )


@router.post("/process", response_model=OrderConfirmationResponse)
async def process_checkout(
    checkout_data: CheckoutRequest,
    user=Depends(role_required(["customer"])),
    db: Session = Depends(get_db)
):
    """Process checkout and convert pending order to processing"""
    system_settings_service.require_verified_email_for_user(db, user["id"], "process checkout")
    
    logger.info(f"Checkout request from user {user.get('id')}, delivery_type {checkout_data.delivery_type}")
    
    # Get pending order
    pending_order = order_service.get_orders_by_status(
        db=db, user_id=user["id"], status="pending"
    )
    
    if not pending_order:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No pending order found"
        )
    
    # Calculate delivery fee
    delivery_fee = Decimal("0.00")
    
    if checkout_data.delivery_type == "delivery":
        # Validate delivery address is provided
        if not checkout_data.delivery_address_id:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Delivery address is required for delivery orders"
            )
        
        # Validate delivery address
        address = db.query(Address).options(
            joinedload(Address.delivery_state)
        ).filter(
            Address.id == checkout_data.delivery_address_id,
            Address.user_id == user["id"]
        ).first()
        
        if not address:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Delivery address not found"
            )
        
        # Get delivery state price
        if address.delivery_state and address.delivery_state.delivery_price:
            delivery_fee = address.delivery_state.delivery_price
        else:
            # Use base price from system settings
            settings = system_settings_service.get_or_create_settings(db)
            delivery_fee = settings.base_delivery_price or Decimal("0.00")

        pending_order.delivery_address = checkout_data.delivery_address_id
    elif checkout_data.delivery_type == "pickup":
        # Pickup - no address needed, no delivery fee
        settings = system_settings_service.get_or_create_settings(db)
        pending_order.pickup_location = settings.store_pickup_location or "Store Location"
        delivery_fee = Decimal("0.00")
    
    # Update order with delivery information
    pending_order.delivery_type = checkout_data.delivery_type
    pending_order.delivery_fee = delivery_fee
    
    # Add delivery fee to total amount
    pending_order.total_amount = Decimal(str(pending_order.total_amount)) + delivery_fee
    
    # Stock was already reserved when the order was created — no re-validation or deduction needed here.
    
    # Don't change status to processing yet - wait for payment confirmation
    
    db.commit()
    db.refresh(pending_order)
    
    # Calculate estimated delivery (7 days from now)
    estimated_delivery = (datetime.now() + timedelta(days=7)).strftime("%Y-%m-%d")
    
    # Generate tracking number (simple implementation)
    tracking_number = f"ALH{pending_order.id.hex[:8].upper()}"
    
    confirmation = OrderConfirmation(
        order_id=pending_order.id,
        total_amount=Decimal(str(pending_order.total_amount)),
        status=pending_order.status,
        estimated_delivery=estimated_delivery,
        tracking_number=tracking_number
    )
    
    # Create order confirmation notification (non-blocking)
    try:
        # Use in-app notification only to avoid email timeout issues
        create_notification(db, {
            "user_id": str(pending_order.buyer_id),
            "type": "order_confirmed",
            "title": "Order Confirmed",
            "message": f"Your order #{str(pending_order.id)[:8]} has been confirmed and is ready for payment. Total: ₦{pending_order.total_amount:,.2f}",
            "priority": "high",
            "channels": ["in_app"],  # Remove email to avoid timeout issues
            "data": {
                "order_id": str(pending_order.id),
                "total_amount": float(pending_order.total_amount),
                "tracking_number": tracking_number,
                "estimated_delivery": estimated_delivery
            }
        })
        logger.info(f"Order confirmation notification created for order {pending_order.id}")
    except Exception as e:
        logger.warning(f"Failed to create order confirmation notification: {e}")
    
    return OrderConfirmationResponse(
        success=True,
        message="Order processed successfully",
        data=confirmation
    )


@router.get("/addresses", response_model=dict)
async def get_checkout_addresses(
    user=Depends(role_required(["customer"])),
    db: Session = Depends(get_db)
):
    """Get user's addresses for checkout"""
    
    addresses = db.query(Address).filter(Address.user_id == user["id"]).all()
    
    return {
        "success": True,
        "message": "Addresses retrieved successfully",
        "data": [
            {
                "id": str(addr.id),
                "title": addr.title,
                "street_address": addr.street_address,
                "city": addr.city,
                "state_province": addr.state_province,
                "postal_code": addr.postal_code,
                "country": addr.country,
                "is_default": addr.is_default,
                "full_address": f"{addr.street_address}, {addr.city}, {addr.state_province}, {addr.postal_code}, {addr.country}"
            }
            for addr in addresses
        ]
    }
