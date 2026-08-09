from fastapi import APIRouter, Depends, HTTPException, status, Request
from sqlalchemy.orm import Session
from typing import Optional, List
import json
from uuid import UUID

from core.auth import role_required, get_current_user
from db.session import get_db
from core.paystack_service import paystack_service
from core.payment_service import payment_service
from core.model import Payment, Order, StoreProfile
from schemas.payment import (
    PaymentInitializeRequest,
    PaymentInitializeResponse,
    PaymentVerifyRequest,
    PaymentVerifyResponse,
    PaymentWebhookData,
    PaymentResponse,
    PaymentListResponse,
    BankTransferInitializeRequest,
    BankTransferInitializeResponse,
)
from core.logging_config import get_logger, log_error
from core.notifications_service import create_notification
from core.system_settings_service import system_settings_service

# Get logger for payment routes
payment_logger = get_logger("routers.payments")

router = APIRouter()

@router.post("/initialize", response_model=PaymentInitializeResponse)
async def initialize_payment(
    request: PaymentInitializeRequest,
    user=Depends(role_required(["customer", "admin"])),
    db: Session = Depends(get_db)
):
    """Unified payment initialization hub"""
    try:
        system_settings_service.require_verified_email_for_user(db, user["id"], "initialize a payment")
        data = payment_service.initialize_payment(
            db=db,
            user_id=user["id"],
            email=request.email,
            amount_kobo=int(request.amount * 100),
            category=request.category,
            order_id=str(request.order_id) if request.order_id else None,
            agreement_id=str(request.agreement_id) if request.agreement_id else None,
            callback_url=request.callback_url,
            metadata=request.metadata,  # passed through to Paystack, not stored on model
            payment_method=request.payment_method
        )
        
        return PaymentInitializeResponse(
            success=True,
            message="Payment initialized successfully",
            data=data
        )
    except HTTPException:
        raise
    except Exception as e:
        payment_logger.error(f"Failed to initialize payment: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/initialize-bank-transfer", response_model=BankTransferInitializeResponse)
async def initialize_bank_transfer(
    request: BankTransferInitializeRequest,
    user=Depends(role_required(["customer", "admin"])),
    db: Session = Depends(get_db)
):
    """Generate a one-time bank account number (Pay with Transfer) for an order or agreement payment"""
    try:
        system_settings_service.require_verified_email_for_user(db, user["id"], "initialize a payment")
        data = payment_service.initialize_bank_transfer_payment(
            db=db,
            user_id=user["id"],
            email=request.email,
            amount_kobo=int(request.amount * 100),
            category=request.category,
            order_id=str(request.order_id) if request.order_id else None,
            agreement_id=str(request.agreement_id) if request.agreement_id else None,
            metadata=request.metadata,
        )

        return BankTransferInitializeResponse(
            success=True,
            message="Bank transfer details generated successfully",
            data=data
        )
    except HTTPException:
        raise
    except Exception as e:
        payment_logger.error(f"Failed to initialize bank transfer payment: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/verify", response_model=PaymentVerifyResponse)
async def verify_payment(
    request: PaymentVerifyRequest,
    user=Depends(role_required(["customer"])),
    db: Session = Depends(get_db)
):
    """Unified payment verification hub"""
    try:
        ps_res = payment_service.verify_transaction(db, request.reference)
        is_success = ps_res.get("status", False) and ps_res.get("data", {}).get("status") == "success"

        if not is_success:
            # Paystack's top-level message often says 'Verification successful' because the API request
            # succeeded, even if the payment itself failed or was abandoned. 
            # We should use the actual transaction status for a more accurate error message.
            tx_status = ps_res.get("data", {}).get("status", "failed")
            error_msg = f"Payment status: {tx_status}"
            if ps_res.get("data", {}).get("gateway_response"):
                error_msg += f" ({ps_res['data']['gateway_response']})"
            elif not ps_res.get("status", False):
                # If the API request itself failed, use its message
                error_msg = ps_res.get("message", "Payment verification failed")

            raise HTTPException(
                status_code=status.HTTP_402_PAYMENT_REQUIRED,
                detail=error_msg
            )

        return PaymentVerifyResponse(
            success=True,
            message=ps_res.get("message", "Payment verified successfully"),
            data=ps_res.get("data", {})
        )
    except HTTPException:
        raise
    except Exception as e:
        payment_logger.error(f"Verification error: {str(e)}")
        raise HTTPException(status_code=500, detail="Verification failed")

@router.post("/webhook")
async def paystack_webhook(request: Request, db: Session = Depends(get_db)):
    """Handle Paystack webhook events"""
    try:
        # Get the raw body
        body = await request.body()
        
        # Verify webhook signature
        signature = request.headers.get("x-paystack-signature")
        if not signature:
            payment_logger.warning("Webhook request missing signature")
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Missing signature"
            )
        
        # Verify signature
        if not paystack_service.verify_webhook_signature(body, signature):
            payment_logger.warning("Webhook signature verification failed")
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Invalid signature"
            )
        
        webhook_data = json.loads(body)
        event = webhook_data.get("event")
        data = webhook_data.get("data", {})
        
        payment_logger.info(f"Processing webhook event: {event}")
        
        # Handle different webhook events
        reference = data.get("reference")
        if not reference:
            payment_logger.warning(f"No reference found in webhook event: {event}")
            return {"status": "ignored", "reason": "no_reference"}
        
        # Find payment record
        payment = db.query(Payment).filter(
            Payment.transaction_id == reference
        ).first()
        
        if not payment:
            payment_logger.warning(f"Payment not found for reference: {reference}")
            return {"status": "ignored", "reason": "payment_not_found"}
        
        # Check if already processed (idempotency)
        if payment.status in ["completed", "failed"]:
            payment_logger.info(f"Payment {reference} already processed with status: {payment.status}")
            return {"status": "ignored", "reason": "already_processed"}
        
        if event == "charge.success":
            # Handle successful payment through unified service
            payment_service.verify_transaction(db, reference)
            payment_logger.info(f"Webhook: Payment verified for {reference}")
            
        else:
            payment_logger.info(f"Unhandled webhook event: {event} for reference: {reference}")
        
        return {"status": "success"}
        
    except Exception as e:
        log_error(payment_logger, "Webhook processing failed", e)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Webhook processing failed"
        )

@router.post("/webhook/test")
async def test_webhook(request: Request, db: Session = Depends(get_db)):
    """Test webhook endpoint for development"""
    try:
        body = await request.body()
        webhook_data = json.loads(body)
        
        payment_logger.info(f"Test webhook received: {webhook_data}")
        
        return {
            "status": "success",
            "message": "Test webhook processed",
            "received_data": webhook_data
        }
        
    except Exception as e:
        log_error(payment_logger, "Test webhook failed", e)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Test webhook failed"
        )

@router.get("/", response_model=PaymentListResponse)
async def list_payments(
    user=Depends(role_required(["customer", "admin"])),
    db: Session = Depends(get_db),
    page: int = 1,
    limit: int = 20
):
    """List payments for the current user"""
    try:
        query = db.query(Payment)

        if user["role"] == "customer":
            query = query.filter(Payment.buyer_id == user["id"])
        # Admin can see all payments

        total = query.count()
        payments = query.order_by(Payment.created_at.desc()).offset((page - 1) * limit).limit(limit).all()

        # Populate the store name manually (Payment model has seller_id, which
        # now points at the single store_profiles row).
        data = []
        for p in payments:
            res = PaymentResponse.model_validate(p)
            if p.seller_id:
                seller = db.query(StoreProfile).filter(StoreProfile.id == p.seller_id).first()
                if seller:
                    res.seller_name = seller.business_name
            data.append(res)

        return PaymentListResponse(
            success=True,
            message="Payments retrieved successfully",
            data=data,
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


@router.post("/refund/{id}", response_model=PaymentResponse)
async def refund_payment(
    id: UUID,
    reason: str = "Requested by admin",
    user=Depends(role_required(["admin"])),
    db: Session = Depends(get_db)
):
    """Refund a successfully processed paystack payment (Admin only)"""
    try:
        payment = payment_service.refund_payment(
            db=db,
            payment_id=str(id),
            admin_id=user["id"],
            reason=reason
        )
        return PaymentResponse.model_validate(payment)
    except HTTPException:
        raise
    except Exception as e:
        payment_logger.error(f"Refund request error: {str(e)}")
        raise HTTPException(status_code=500, detail="Refund request failed")
