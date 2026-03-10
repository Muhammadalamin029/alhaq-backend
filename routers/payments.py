from fastapi import APIRouter, Depends, HTTPException, status, Request
from sqlalchemy.orm import Session
from typing import Optional, List
import json
from uuid import UUID

from core.auth import role_required, get_current_user
from db.session import get_db
from core.paystack_service import paystack_service
from core.payment_service import payment_service
from core.model import Payment, Order, SellerProfile
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
from core.notifications_service import create_notification

# Get logger for payment routes
payment_logger = get_logger("routers.payments")

router = APIRouter()

@router.post("/initialize", response_model=PaymentInitializeResponse)
async def initialize_payment(
    request: PaymentInitializeRequest,
    user=Depends(role_required(["customer"])),
    db: Session = Depends(get_db)
):
    """Unified payment initialization hub"""
    try:
        data = payment_service.initialize_payment(
            db=db,
            user_id=user["id"],
            email=request.email,
            amount_kobo=int(request.amount * 100),
            category=request.category,
            order_id=str(request.order_id) if request.order_id else None,
            agreement_id=str(request.agreement_id) if request.agreement_id else None,
            callback_url=request.callback_url,
            metadata=request.metadata
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

@router.post("/verify", response_model=PaymentVerifyResponse)
async def verify_payment(
    request: PaymentVerifyRequest,
    user=Depends(role_required(["customer", "seller"])),
    db: Session = Depends(get_db)
):
    """Unified payment verification hub"""
    try:
        ps_res = payment_service.verify_transaction(db, request.reference)
        is_success = ps_res.get("status", False) and ps_res.get("data", {}).get("status") == "success"
        
        return PaymentVerifyResponse(
            success=is_success,
            message=ps_res.get("message", "Verification finished"),
            data=ps_res.get("data", {})
        )
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
            
        elif event in ["transfer.success", "transfer.failed"]:
            # Handle payout transfers
            from core.seller_payout_service import seller_payout_service
            seller_payout_service.handle_payout_webhook(db, data)
            payment_logger.info(f"Webhook: Transfer {event} processed for {reference}")
            
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
        payments = query.order_by(Payment.created_at.desc()).offset((page - 1) * limit).limit(limit).all()
        
        # Populate seller info manually if not using relationship (or use relationship if defined)
        # Note: Payment model has seller_id. We can use it to fetch seller info.
        data = []
        for p in payments:
            res = PaymentResponse.model_validate(p)
            if p.seller_id:
                seller = db.query(SellerProfile).filter(SellerProfile.id == p.seller_id).first()
                if seller:
                    res.seller_name = seller.business_name
                    res.seller_type = seller.seller_type
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
