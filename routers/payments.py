from fastapi import APIRouter, Depends, HTTPException, status, Request
from fastapi.responses import HTMLResponse
from sqlalchemy import String, cast, or_
from sqlalchemy.orm import Session
from typing import Optional, List
import json
from uuid import UUID

from core.auth import role_required, get_current_user
from db.session import get_db
from core.flutterwave_service import flutterwave_service
from core.payment_service import payment_service
from core import receipt_service
from core.model import Payment, Order, StoreProfile, Profile, User
from schemas.payment import (
    CardAuthorizeRequest,
    CardChargeRequest,
    CardValidateRequest,
    PaymentInitializeResponse,
    PaymentVerifyRequest,
    PaymentVerifyResponse,
    PaymentWebhookData,
    PaymentResponse,
    PaymentListResponse,
    BankTransferInitializeRequest,
    BankTransferInitializeResponse,
    ReceiptResponse,
)
from core.logging_config import get_logger, log_error
from core.notifications_service import create_notification
from core.system_settings_service import system_settings_service

# Get logger for payment routes
payment_logger = get_logger("routers.payments")

router = APIRouter()

@router.post("/charge-card", response_model=PaymentInitializeResponse)
async def charge_card(
    request: CardChargeRequest,
    user=Depends(role_required(["customer", "admin"])),
    db: Session = Depends(get_db)
):
    """Step 1 of the Direct-API card flow.

    Charges the card via Flutterwave and returns ``next_step`` (pin | avs |
    otp | redirect | success | failed) plus ``tx_ref`` for the follow-up
    calls. Raw card fields are forwarded over TLS and never stored.
    """
    from decimal import Decimal
    try:
        system_settings_service.require_verified_email_for_user(db, user["id"], "make a card payment")
        data = payment_service.charge_card_payment(
            db=db,
            user_id=user["id"],
            email=request.email,
            amount_naira=Decimal(str(request.amount)),
            category=request.category,
            card_number=request.card_number,
            cvv=request.cvv,
            expiry_month=request.expiry_month,
            expiry_year=request.expiry_year,
            order_id=str(request.order_id) if request.order_id else None,
            agreement_id=str(request.agreement_id) if request.agreement_id else None,
            fullname=request.fullname,
            phone_number=request.phone_number,
            redirect_url=request.redirect_url,
            metadata=request.metadata,
            payment_method=request.payment_method
        )

        return PaymentInitializeResponse(
            success=data.get("next_step") not in ("failed",),
            message="Card charge processed",
            data=data
        )
    except HTTPException:
        raise
    except Exception as e:
        payment_logger.error(f"Failed to charge card: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/charge-card/authorize", response_model=PaymentInitializeResponse)
async def authorize_card(
    request: CardAuthorizeRequest,
    user=Depends(role_required(["customer", "admin"])),
    db: Session = Depends(get_db)
):
    """Step 2: resubmit the card payload with PIN/AVS authorization."""
    try:
        data = payment_service.authorize_card_payment(
            db=db,
            tx_ref=request.tx_ref,
            card_number=request.card_number,
            cvv=request.cvv,
            expiry_month=request.expiry_month,
            expiry_year=request.expiry_year,
            authorization=request.authorization,
            email=request.email,
            fullname=request.fullname,
            phone_number=request.phone_number,
            redirect_url=request.redirect_url,
        )

        return PaymentInitializeResponse(
            success=data.get("next_step") not in ("failed",),
            message="Card authorization processed",
            data=data
        )
    except HTTPException:
        raise
    except Exception as e:
        payment_logger.error(f"Failed to authorize card charge: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/charge-card/validate", response_model=PaymentInitializeResponse)
async def validate_card(
    request: CardValidateRequest,
    user=Depends(role_required(["customer", "admin"])),
    db: Session = Depends(get_db)
):
    """Step 3: validate the charge with the OTP sent to the customer."""
    try:
        data = payment_service.validate_card_payment(
            db=db,
            tx_ref=request.tx_ref,
            otp=request.otp,
        )

        return PaymentInitializeResponse(
            success=data.get("next_step") == "success",
            message="Card charge validated",
            data=data
        )
    except HTTPException:
        raise
    except Exception as e:
        payment_logger.error(f"Failed to validate card charge: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/initialize-bank-transfer", response_model=BankTransferInitializeResponse)
async def initialize_bank_transfer(
    request: BankTransferInitializeRequest,
    user=Depends(role_required(["customer", "admin"])),
    db: Session = Depends(get_db)
):
    """Generate a one-time bank account number (Pay with Transfer) for an order or agreement payment"""
    from decimal import Decimal
    try:
        system_settings_service.require_verified_email_for_user(db, user["id"], "initialize a payment")
        data = payment_service.initialize_bank_transfer_payment(
            db=db,
            user_id=user["id"],
            email=request.email,
            amount_naira=Decimal(str(request.amount)),
            category=request.category,
            order_id=str(request.order_id) if request.order_id else None,
            agreement_id=str(request.agreement_id) if request.agreement_id else None,
            metadata=request.metadata,
            fullname=request.fullname,
            phone_number=request.phone_number,
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
    """Unified payment verification hub (Flutterwave verify + ledger match)"""
    try:
        result = payment_service.verify_transaction(db, request.reference, transaction_id=request.transaction_id)
        if not result.get("completed"):
            # Flutterwave's top-level message often says 'success' because the API
            # request succeeded, even if the payment itself failed or is pending.
            tx_status = (result.get("data") or {}).get("status", "pending")
            error_msg = f"Payment status: {tx_status}"
            if (result.get("data") or {}).get("processor_response"):
                error_msg += f" ({result['data']['processor_response']})"
            elif not result.get("status", False):
                error_msg = result.get("message", "Payment verification failed")

            raise HTTPException(
                status_code=status.HTTP_402_PAYMENT_REQUIRED,
                detail=error_msg
            )

        return PaymentVerifyResponse(
            success=True,
            message=result.get("message", "Payment verified successfully"),
            data=result.get("data", {})
        )
    except HTTPException:
        raise
    except Exception as e:
        payment_logger.error(f"Verification error: {str(e)}")
        raise HTTPException(status_code=500, detail="Verification failed")

@router.post("/webhook")
async def flutterwave_webhook(request: Request, db: Session = Depends(get_db)):
    """Handle Flutterwave webhook events (charge.completed for cards, bank
    transfers and tokenized mandate installments)."""
    try:
        # Get the raw body
        body = await request.body()

        # Verify webhook signature (verif-hash / flutterwave-signature)
        if not flutterwave_service.verify_webhook_signature(dict(request.headers), body):
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
        tx_ref = data.get("tx_ref")
        if not tx_ref:
            payment_logger.warning(f"No tx_ref found in webhook event: {event}")
            return {"status": "ignored", "reason": "no_reference"}

        # Tokenized installment charges that have no local Payment row yet are
        # handled by the mandate hook; anything with a Payment falls through.
        mandate_result = payment_service.handle_mandate_webhook(db, event, tx_ref, data)
        if mandate_result is not None:
            return mandate_result

        # Find payment record
        payment = db.query(Payment).filter(
            (Payment.reference == tx_ref) | (Payment.transaction_id == tx_ref)
        ).first()

        if not payment:
            payment_logger.warning(f"Payment not found for reference: {tx_ref}")
            return {"status": "ignored", "reason": "payment_not_found"}

        # Check if already processed (idempotency)
        if payment.status in ["completed", "failed"]:
            payment_logger.info(f"Payment {tx_ref} already processed with status: {payment.status}")
            return {"status": "ignored", "reason": "already_processed"}

        if event == "charge.completed":
            # Re-verify via API (failsafe) and complete through unified service
            payment_service.verify_transaction(db, tx_ref, transaction_id=data.get("id"))
            payment_logger.info(f"Webhook: Payment verified for {tx_ref}")

        else:
            payment_logger.info(f"Unhandled webhook event: {event} for reference: {tx_ref}")

        return {"status": "success"}

    except HTTPException:
        # Intended client errors (400s) must propagate — never convert to 500,
        # or Flutterwave treats them as server failures and spams retries.
        raise
    except Exception as e:
        log_error(payment_logger, "Webhook processing failed", e)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Webhook processing failed"
        )

@router.post("/webhook/test")
async def test_webhook(request: Request, db: Session = Depends(get_db)):
    """Test webhook endpoint for development — disabled in production."""
    from core.config import settings as app_settings
    if str(getattr(app_settings, "ENVIRONMENT", "development")).lower() == "production":
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Not found"
        )
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
    limit: int = 20,
    search: Optional[str] = None,
    status: Optional[str] = None,
    category: Optional[str] = None
):
    """List payments for the current user.

    Admins see every payment; customers only their own. All filters are applied
    server-side so they stay accurate beyond the first page of results.
    """
    try:
        query = db.query(Payment)

        if user["role"] == "customer":
            query = query.filter(Payment.buyer_id == user["id"])
        # Admin can see all payments

        if status and status != "all":
            query = query.filter(Payment.status == status)
        if category and category != "all":
            query = query.filter(Payment.payment_category == category)

        if search:
            like = f"%{search.strip()}%"
            # Profile.id is both the buyer_id and the users.id (shared PK), so a
            # single round-trip through Profile gives us the buyer's email too.
            query = query.outerjoin(Profile, Payment.buyer_id == Profile.id)
            query = query.outerjoin(User, Profile.id == User.id)
            query = query.filter(
                or_(
                    Payment.receipt_number.ilike(like),
                    Payment.reference.ilike(like),
                    Payment.transaction_id.ilike(like),
                    cast(Payment.order_id, String).ilike(like),
                    cast(Payment.agreement_id, String).ilike(like),
                    User.email.ilike(like),
                    Profile.name.ilike(like),
                )
            )

        total = query.count()
        payments = query.order_by(Payment.created_at.desc()).offset((page - 1) * limit).limit(limit).all()

        # Batch-load the buyer profile/user and seller for this page's rows so the
        # response can expose buyer_name/buyer_email/seller_name without an N+1
        # query per payment.
        buyer_ids = {p.buyer_id for p in payments if p.buyer_id}
        profiles = {}
        buyers = {}
        if buyer_ids:
            profiles = {
                profile.id: profile
                for profile in db.query(Profile).filter(Profile.id.in_(buyer_ids)).all()
            }
            buyers = {
                buyer.id: buyer
                for buyer in db.query(User).filter(User.id.in_(buyer_ids)).all()
            }

        seller_ids = {p.seller_id for p in payments if p.seller_id}
        sellers = {}
        if seller_ids:
            sellers = {
                seller.id: seller
                for seller in db.query(StoreProfile).filter(StoreProfile.id.in_(seller_ids)).all()
            }

        data = []
        for p in payments:
            res = PaymentResponse.model_validate(p)
            profile = profiles.get(p.buyer_id)
            if profile:
                res.buyer_name = profile.name
            buyer = buyers.get(p.buyer_id)
            if buyer:
                res.buyer_email = buyer.email
            if p.seller_id and p.seller_id in sellers:
                res.seller_name = sellers[p.seller_id].business_name
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


@router.get("/{id}/receipt", response_model=ReceiptResponse)
async def get_payment_receipt(
    id: UUID,
    user=Depends(role_required(["customer", "admin"])),
    db: Session = Depends(get_db)
):
    """Get a structured receipt for a single payment."""
    receipt = receipt_service.get_receipt(db, user, id)
    if not receipt:
        raise HTTPException(status_code=404, detail="Receipt not found or unauthorized")
    return receipt


@router.get("/{id}/receipt/html", response_class=HTMLResponse)
async def get_payment_receipt_html(
    id: UUID,
    user=Depends(role_required(["customer", "admin"])),
    db: Session = Depends(get_db)
):
    """Render a payment receipt as printable HTML (browser print-to-PDF)."""
    receipt = receipt_service.get_receipt(db, user, id)
    if not receipt:
        raise HTTPException(status_code=404, detail="Receipt not found or unauthorized")
    return HTMLResponse(content=receipt_service.render_receipt_html(receipt))


@router.get("/{id}", response_model=PaymentResponse)
async def get_payment(
    id: UUID,
    user=Depends(role_required(["customer", "admin"])),
    db: Session = Depends(get_db)
):
    """Get a single payment. Admins may see any payment; customers only their own."""
    try:
        payment = db.query(Payment).filter(Payment.id == id).first()
        if not payment:
            raise HTTPException(status_code=404, detail="Payment not found")

        if user["role"] != "admin" and str(payment.buyer_id) != str(user["id"]):
            raise HTTPException(status_code=404, detail="Payment not found")

        res = PaymentResponse.model_validate(payment)
        profile = db.query(Profile).filter(Profile.id == payment.buyer_id).first()
        if profile:
            res.buyer_name = profile.name
        buyer = db.query(User).filter(User.id == payment.buyer_id).first()
        if buyer:
            res.buyer_email = buyer.email
        if payment.seller_id:
            seller = db.query(StoreProfile).filter(StoreProfile.id == payment.seller_id).first()
            if seller:
                res.seller_name = seller.business_name
        return res
    except HTTPException:
        raise
    except Exception as e:
        log_error(payment_logger, f"Failed to get payment {id}", e)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to retrieve payment"
        )


@router.post("/refund/{id}", response_model=PaymentResponse)
async def refund_payment(
    id: UUID,
    reason: str = "Requested by admin",
    user=Depends(role_required(["admin"])),
    db: Session = Depends(get_db)
):
    """Refund a successfully processed Flutterwave payment (Admin only)"""
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
