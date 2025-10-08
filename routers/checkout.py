from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session, joinedload
from decimal import Decimal
from datetime import datetime, timedelta
from uuid import UUID

from db.session import get_db
from core.auth import role_required
from core.model import Order, OrderItem, Address, Product
from core.order import order_service
from schemas.checkout import (
    CheckoutRequest, 
    CheckoutSummary, 
    CheckoutResponse,
    OrderConfirmation,
    OrderConfirmationResponse
)
from schemas.order import OrderResponse
from core.notifications_service import create_notification

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
    # Note: Customer pays delivery directly to logistics provider
    # No delivery fee included in order total
    shipping_fee = Decimal("0.00")  # Customer pays delivery separately
    tax = Decimal("0.00")  # No tax for now
    total = subtotal + shipping_fee + tax
    
    items_count = len(pending_order.order_items)
    
    summary = CheckoutSummary(
        subtotal=subtotal,
        shipping_fee=shipping_fee,
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
    
    # Log the incoming request for debugging
    print(f"Checkout request received: {checkout_data}")
    print(f"User ID: {user.get('id')}")
    print(f"Delivery address ID: {checkout_data.delivery_address_id}")
    
    # Get pending order
    pending_order = order_service.get_orders_by_status(
        db=db, user_id=user["id"], status="pending"
    )
    
    if not pending_order:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No pending order found"
        )
    
    # Validate delivery address
    address = db.query(Address).filter(
        Address.id == checkout_data.delivery_address_id,
        Address.user_id == user["id"]
    ).first()
    
    if not address:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Delivery address not found"
        )
    
    # Validate stock availability for all items
    for item in pending_order.order_items:
        product = db.query(Product).filter(Product.id == item.product_id).first()
        if not product:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Product {item.product_id} not found"
            )
        
        if product.stock_quantity < item.quantity:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Insufficient stock for {product.name}. Available: {product.stock_quantity}, Required: {item.quantity}"
            )
    
    # Reserve stock for all items
    for item in pending_order.order_items:
        product = db.query(Product).filter(Product.id == item.product_id).first()
        product.stock_quantity -= item.quantity
    
    # Update order with delivery address (keep as pending until payment)
    pending_order.delivery_address = checkout_data.delivery_address_id
    # Don't change status to processing yet - wait for payment confirmation
    
    # Add notes if provided
    if checkout_data.notes:
        # In a real app, you might have an order_notes field or separate notes table
        pass
    
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
        print(f"Order confirmation notification created for order {pending_order.id}")
    except Exception as e:
        # Log error but don't fail the checkout
        print(f"Failed to create order confirmation notification: {e}")
        # Continue with checkout even if notification fails
    
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