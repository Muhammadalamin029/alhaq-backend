from fastapi import APIRouter, Depends, HTTPException, status, Request
from sqlalchemy.orm import Session
from typing import Optional
import hashlib
import hmac
import json

from core.auth import role_required, get_current_user
from db.session import get_db
from core.paystack_service import paystack_service
from core.model import Payment, Order, User
from schemas.payment import (
    PaymentInitializeRequest,
    PaymentInitializeResponse,
    PaymentVerifyRequest,
    PaymentVerifyResponse,
    PaymentWebhookData,
    TransferRecipientRequest,
    TransferRecipientResponse,
    TransferRequest,
    TransferResponse,
    BankResponse,
    PaymentResponse,
    PaymentListResponse
)
from core.logging_config import get_logger, log_error

# Get logger for payment routes
payment_logger = get_logger("routers.payments")

router = APIRouter()

@router.post("/initialize", response_model=PaymentInitializeResponse)
async def initialize_payment(
    request: PaymentInitializeRequest,
    user=Depends(role_required(["customer"])),
    db: Session = Depends(get_db)
):
    """Initialize a Paystack payment"""
    try:
        # Get the order
        order = db.query(Order).filter(
            Order.id == request.order_id,
            Order.buyer_id == user["id"]
        ).first()
        
        if not order:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Order not found"
            )
        
        if order.status != "pending":
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Order is not in pending status"
            )
        
        # Generate unique reference
        import uuid
        reference = f"ALHAQ_{uuid.uuid4().hex[:10].upper()}"
        
        # Initialize Paystack transaction
        try:
            paystack_response = paystack_service.initialize_transaction(
                email=request.email,
                amount=request.amount,
                reference=reference,
                metadata={
                    "order_id": str(order.id),
                    "user_id": user["id"],
                    "user_email": request.email
                }
            )
            
            if not paystack_response.get("status"):
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Failed to initialize payment"
                )
        except Exception as e:
            payment_logger.error(f"Paystack initialization error: {str(e)}")
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Payment service error: {str(e)}"
            )
        
        # Store payment record
        # Try to get seller_id from the first order item
        # In a multi-vendor system, you might need to create separate payments for each seller
        seller_id = None
        if order.order_items:
            first_item = order.order_items[0]
            if hasattr(first_item, 'product') and first_item.product:
                seller_id = first_item.product.seller_id
        
        # If no seller_id found and the column is NOT NULL, we need to handle this
        # For now, we'll try to create the payment and handle the error if it fails
        try:
            payment = Payment(
                order_id=order.id,
                buyer_id=user["id"],
                seller_id=seller_id,  # Will be None if no seller found
                amount=request.amount / 100,  # Convert from kobo to NGN
                status="pending",
                payment_method="paystack",
                transaction_id=reference
            )
        except Exception as db_error:
            if "seller_id" in str(db_error) and "null value" in str(db_error):
                # Database still has NOT NULL constraint on seller_id
                payment_logger.error(f"Database constraint error: {db_error}")
                raise HTTPException(
                    status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                    detail="Payment system configuration error. Please contact support."
                )
            else:
                raise db_error
        db.add(payment)
        db.commit()
        
        payment_logger.info(f"Payment initialized for order {order.id}: {reference}")
        
        return PaymentInitializeResponse(
            success=True,
            message="Payment initialized successfully",
            data=paystack_response["data"]
        )
        
    except HTTPException:
        raise
    except Exception as e:
        log_error(payment_logger, f"Failed to initialize payment for order {request.order_id}", e)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to initialize payment"
        )

@router.post("/verify", response_model=PaymentVerifyResponse)
async def verify_payment(
    request: PaymentVerifyRequest,
    user=Depends(role_required(["customer"])),
    db: Session = Depends(get_db)
):
    """Verify a Paystack payment"""
    try:
        # Verify with Paystack
        paystack_response = paystack_service.verify_transaction(request.reference)
        
        if not paystack_response.get("status"):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Payment verification failed"
            )
        
        transaction_data = paystack_response["data"]
        
        # Get payment record
        payment = db.query(Payment).filter(
            Payment.transaction_id == request.reference
        ).first()
        
        if not payment:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Payment record not found"
            )
        
        # Update payment status
        if transaction_data["status"] == "success":
            payment.status = "completed"
            
            # Update order status
            order = db.query(Order).filter(Order.id == payment.order_id).first()
            if order:
                order.status = "processing"
            
            payment_logger.info(f"Payment verified successfully: {request.reference}")
        else:
            payment.status = "failed"
            payment_logger.warning(f"Payment verification failed: {request.reference}")
        
        db.commit()
        
        return PaymentVerifyResponse(
            success=True,
            message="Payment verified successfully",
            data=transaction_data
        )
        
    except HTTPException:
        raise
    except Exception as e:
        log_error(payment_logger, f"Failed to verify payment {request.reference}", e)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to verify payment"
        )

@router.post("/webhook")
async def paystack_webhook(request: Request, db: Session = Depends(get_db)):
    """Handle Paystack webhook events"""
    try:
        # Get the raw body
        body = await request.body()
        
        # Verify webhook signature
        signature = request.headers.get("x-paystack-signature")
        if not signature:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Missing signature"
            )
        
        # Verify signature (implement proper verification)
        # For now, we'll process the webhook without verification
        # In production, implement proper HMAC verification
        
        webhook_data = json.loads(body)
        event = webhook_data.get("event")
        data = webhook_data.get("data", {})
        
        if event == "charge.success":
            # Handle successful payment
            reference = data.get("reference")
            if reference:
                payment = db.query(Payment).filter(
                    Payment.transaction_id == reference
                ).first()
                
                if payment and payment.status == "pending":
                    payment.status = "completed"
                    
                    # Update order status
                    order = db.query(Order).filter(Order.id == payment.order_id).first()
                    if order:
                        order.status = "processing"
                    
                    db.commit()
                    payment_logger.info(f"Webhook: Payment completed for {reference}")
        
        elif event == "charge.failed":
            # Handle failed payment
            reference = data.get("reference")
            if reference:
                payment = db.query(Payment).filter(
                    Payment.transaction_id == reference
                ).first()
                
                if payment and payment.status == "pending":
                    payment.status = "failed"
                    db.commit()
                    payment_logger.warning(f"Webhook: Payment failed for {reference}")
        
        return {"status": "success"}
        
    except Exception as e:
        log_error(payment_logger, "Webhook processing failed", e)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Webhook processing failed"
        )

@router.get("/banks", response_model=BankResponse)
async def get_banks():
    """Get list of supported banks"""
    try:
        banks_data = paystack_service.get_banks()
        
        return BankResponse(
            success=True,
            message="Banks retrieved successfully",
            data=banks_data.get("data", [])
        )
        
    except Exception as e:
        log_error(payment_logger, "Failed to get banks", e)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to get banks"
        )

@router.post("/transfer-recipient", response_model=TransferRecipientResponse)
async def create_transfer_recipient(
    request: TransferRecipientRequest,
    user=Depends(role_required(["seller", "admin"])),
    db: Session = Depends(get_db)
):
    """Create a transfer recipient for seller payouts"""
    try:
        recipient_data = paystack_service.create_transfer_recipient(
            name=request.name,
            account_number=request.account_number,
            bank_code=request.bank_code,
            email=request.email
        )
        
        return TransferRecipientResponse(
            success=True,
            message="Transfer recipient created successfully",
            data=recipient_data["data"]
        )
        
    except Exception as e:
        log_error(payment_logger, f"Failed to create transfer recipient for {request.email}", e)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to create transfer recipient"
        )

@router.post("/transfer", response_model=TransferResponse)
async def initiate_transfer(
    request: TransferRequest,
    user=Depends(role_required(["admin"])),
    db: Session = Depends(get_db)
):
    """Initiate a transfer to a seller"""
    try:
        transfer_data = paystack_service.initiate_transfer(
            amount=request.amount,
            recipient_code=request.recipient_code,
            reference=request.reference,
            reason=request.reason
        )
        
        return TransferResponse(
            success=True,
            message="Transfer initiated successfully",
            data=transfer_data["data"]
        )
        
    except Exception as e:
        log_error(payment_logger, f"Failed to initiate transfer {request.reference}", e)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to initiate transfer"
        )

@router.get("/", response_model=PaymentListResponse)
async def list_payments(
    user=Depends(role_required(["customer", "seller", "admin"])),
    db: Session = Depends(get_db),
    page: int = 1,
    limit: int = 20
):
    """List payments for the current user"""
    try:
        query = db.query(Payment)
        
        if user["role"] == "customer":
            query = query.filter(Payment.buyer_id == user["id"])
        elif user["role"] == "seller":
            query = query.filter(Payment.seller_id == user["id"])
        # Admin can see all payments
        
        total = query.count()
        payments = query.offset((page - 1) * limit).limit(limit).all()
        
        return PaymentListResponse(
            success=True,
            message="Payments retrieved successfully",
            data=[PaymentResponse.model_validate(p) for p in payments],
            pagination={
                "page": page,
                "limit": limit,
                "total": total,
                "total_pages": (total + limit - 1) // limit
            }
        )
        
    except Exception as e:
        log_error(payment_logger, f"Failed to list payments for user {user['id']}", e)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to retrieve payments"
        )
