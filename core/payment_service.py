from sqlalchemy.orm import Session
from typing import Optional, Dict, Any
from decimal import Decimal
import uuid
import logging
from datetime import datetime, timezone
from fastapi import HTTPException

from core.model import (
    Payment, Order, OrderItem, GeneralAgreement,
    GeneralInspection, Property, PropertyUnit, PaymentMandate, User
)
from core.paystack_service import paystack_service
from core.notifications_service import create_notification
from core.redis_client import redis_client

logger = logging.getLogger(__name__)

BANK_TRANSFER_EXPIRY_PREFIX = "bank_transfer_expiry:"


class PaymentService:
    def __init__(self):
        self.paystack = paystack_service

    def initialize_payment(
        self, 
        db: Session, 
        user_id: str, 
        email: str, 
        amount_kobo: int, 
        category: str,
        order_id: Optional[str] = None,
        agreement_id: Optional[str] = None,
        callback_url: Optional[str] = None,
        metadata: Optional[Dict] = None,
        payment_method: str = "paystack"
    ) -> Dict[str, Any]:
        """Unified payment initialization for Orders and Asset Agreements"""
        if payment_method != "paystack":
            raise HTTPException(status_code=400, detail="Manual payments have been removed. Please use Paystack.")
        
        # 1. Validation based on category
        if category == "order" and not order_id:
            raise HTTPException(status_code=400, detail="order_id is required for order payments")
        if category in ["asset_deposit", "asset_installment", "full_pay"] and not agreement_id:
            raise HTTPException(status_code=400, detail="agreement_id is required for asset payments")

        # 2. Check if we have an existing pending payment and reuse it
        existing_payment = db.query(Payment).filter(
            Payment.buyer_id == user_id,
            Payment.status == "pending",
            Payment.payment_category == category
        )
        if order_id: existing_payment = existing_payment.filter(Payment.order_id == order_id)
        if agreement_id: existing_payment = existing_payment.filter(Payment.agreement_id == agreement_id)

        existing_payment = existing_payment.first()

        # 4. Infer payment_type if missing in metadata
        payment_type = (metadata or {}).get("payment_type")
        if not payment_type:
            if category == "asset_deposit": payment_type = "deposit"
            elif category == "asset_installment": payment_type = "installment"
            elif category == "order": payment_type = "order"
            elif category == "full_pay": payment_type = "full_pay"

        # Get seller_id if applicable
        seller_id = None
        if agreement_id:
            agreement = db.query(GeneralAgreement).filter(GeneralAgreement.id == agreement_id).first()
            if agreement:
                seller_id = agreement.seller_id
        elif order_id:
            # For orders, we might have multiple sellers, so seller_id at the payment level might be None 
            # and handled per item or per split. But for simplicity if it's single seller we can set it.
            pass
        
        if existing_payment:
            # Re-initialize with Paystack if it's old or just return existing
            logger.info(f"Re-using existing pending payment for {category}: {existing_payment.id}")
            # We update the amount in case it changed
            existing_payment.amount = Decimal(amount_kobo) / 100
            
        # 3. Generate unique reference
        reference = f"LEL_{uuid.uuid4().hex[:10].upper()}"

        # 4. Prepare metadata for Paystack
        ps_metadata = {
            "user_id": str(user_id),
            "category": category,
            "order_id": str(order_id) if order_id else None,
            "agreement_id": str(agreement_id) if agreement_id else None,
            **(metadata or {})
        }

        # 5. Initialize Paystack transaction
        ps_res = self.paystack.initialize_transaction(
            email=email,
            amount=amount_kobo,
            reference=reference,
            metadata=ps_metadata,
            callback_url=callback_url
        )

        if not ps_res.get("status"):
            raise HTTPException(status_code=400, detail="Paystack initialization failed")

        # 6. Save or Update record
        if existing_payment:
            payment = existing_payment
            payment.transaction_id = reference
            payment.reference = reference
            payment.authorization_url = ps_res["data"]["authorization_url"]
            payment.access_code = ps_res["data"]["access_code"]
        else:
            payment = Payment(
                order_id=order_id,
                agreement_id=agreement_id,
                buyer_id=user_id,
                seller_id=seller_id,
                amount=Decimal(amount_kobo) / 100,
                status="pending",
                payment_category=category,
                payment_type=payment_type,
                transaction_id=reference,
                reference=reference,
                authorization_url=ps_res["data"]["authorization_url"],
                access_code=ps_res["data"]["access_code"],
                payment_method=payment_method
            )
            db.add(payment)
        
        # 7. Specific link logic — update order and all its items to "processing"
        if category == "order":
            order = db.query(Order).filter(Order.id == order_id).first()
            if order:
                order.payment_url = ps_res["data"]["authorization_url"]
                order.payment_reference = reference
                order.status = "processing"
                db.query(OrderItem).filter(OrderItem.order_id == order_id).update(
                    {"status": "processing"}, synchronize_session=False
                )

        db.commit()
        return ps_res["data"]

    def _normalize_bank_transfer_details(self, data: Dict[str, Any]) -> Dict[str, Optional[str]]:
        """Defensively extract account details from a Paystack /charge bank_transfer response.

        Paystack returns account_number/account_name/bank/account_expires_at at the
        top level of `data` (not nested under a `bank_transfer` key); the nested
        lookups are kept as a fallback in case the shape differs across API versions.
        """
        bt = data.get("bank_transfer") or {}
        bank = data.get("bank") or bt.get("bank")
        if isinstance(bank, dict):
            bank_name = bank.get("name") or data.get("bank_name") or bt.get("bank_name") or ""
        else:
            bank_name = data.get("bank_name") or bt.get("bank_name") or (bank if isinstance(bank, str) else "") or ""

        return {
            "account_number": data.get("account_number") or bt.get("account_number") or bt.get("transfer_account") or "",
            "account_name": data.get("account_name") or bt.get("account_name") or "",
            "bank_name": bank_name,
            "expires_at": data.get("account_expires_at") or bt.get("account_expires_at") or bt.get("expires_at"),
        }

    def initialize_bank_transfer_payment(
        self,
        db: Session,
        user_id: str,
        email: str,
        amount_kobo: int,
        category: str,
        order_id: Optional[str] = None,
        agreement_id: Optional[str] = None,
        metadata: Optional[Dict] = None,
    ) -> Dict[str, Any]:
        """Generate a one-time 'Pay with Transfer' account number for an order or agreement payment"""
        # 1. Validation based on category
        if category == "order" and not order_id:
            raise HTTPException(status_code=400, detail="order_id is required for order payments")
        if category in ["asset_deposit", "asset_installment", "full_pay"] and not agreement_id:
            raise HTTPException(status_code=400, detail="agreement_id is required for asset payments")

        # 2. Check if we have an existing pending payment and reuse it
        existing_payment = db.query(Payment).filter(
            Payment.buyer_id == user_id,
            Payment.status == "pending",
            Payment.payment_category == category
        )
        if order_id: existing_payment = existing_payment.filter(Payment.order_id == order_id)
        if agreement_id: existing_payment = existing_payment.filter(Payment.agreement_id == agreement_id)

        existing_payment = existing_payment.first()
        amount_naira = Decimal(amount_kobo) / 100

        # 2b. Reuse existing bank transfer details if still valid for this amount
        if existing_payment and existing_payment.transaction_metadata:
            cached = existing_payment.transaction_metadata
            cached_bank_transfer = cached.get("bank_transfer") if cached.get("channel") == "bank_transfer" else None
            if cached_bank_transfer and cached_bank_transfer.get("account_number") and existing_payment.amount == amount_naira:
                is_expired = not redis_client.exists(f"{BANK_TRANSFER_EXPIRY_PREFIX}{existing_payment.reference}")

                if not is_expired:
                    logger.info(f"Reusing existing bank transfer account for {category}: {existing_payment.id}")
                    return {
                        "account_number": cached_bank_transfer["account_number"],
                        "account_name": cached_bank_transfer.get("account_name", ""),
                        "bank_name": cached_bank_transfer.get("bank_name", ""),
                        "amount": amount_naira,
                        "reference": existing_payment.reference,
                        "expires_at": cached_bank_transfer.get("expires_at"),
                        "currency": "NGN",
                    }

        # 3. Infer payment_type if missing in metadata
        payment_type = (metadata or {}).get("payment_type")
        if not payment_type:
            if category == "asset_deposit": payment_type = "deposit"
            elif category == "asset_installment": payment_type = "installment"
            elif category == "order": payment_type = "order"
            elif category == "full_pay": payment_type = "full_pay"

        # Get seller_id if applicable
        seller_id = None
        if agreement_id:
            agreement = db.query(GeneralAgreement).filter(GeneralAgreement.id == agreement_id).first()
            if agreement:
                seller_id = agreement.seller_id

        if existing_payment:
            logger.info(f"Re-using existing pending payment for {category}: {existing_payment.id}")
            existing_payment.amount = amount_naira

        # 4. Generate unique reference
        reference = f"LEL_{uuid.uuid4().hex[:10].upper()}"

        # 5. Prepare metadata for Paystack
        ps_metadata = {
            "user_id": str(user_id),
            "category": category,
            "order_id": str(order_id) if order_id else None,
            "agreement_id": str(agreement_id) if agreement_id else None,
            **(metadata or {})
        }

        # 6. Initiate the Pay with Transfer charge
        ps_res = self.paystack.charge_bank_transfer(
            email=email,
            amount=amount_kobo,
            reference=reference,
            metadata=ps_metadata,
        )

        if not ps_res.get("status"):
            raise HTTPException(status_code=400, detail=ps_res.get("message", "Paystack bank transfer initialization failed"))

        bank_details = self._normalize_bank_transfer_details(ps_res["data"])
        if not bank_details["account_number"]:
            logger.error(f"Bank transfer charge for {reference} returned no account number: {ps_res}")
            raise HTTPException(status_code=502, detail="Bank transfer details unavailable from Paystack")

        if bank_details["expires_at"]:
            try:
                expiry_dt = datetime.fromisoformat(str(bank_details["expires_at"]).replace("Z", "+00:00"))
                ttl_seconds = max(30, int((expiry_dt - datetime.now(timezone.utc)).total_seconds()))
                redis_client.set(f"{BANK_TRANSFER_EXPIRY_PREFIX}{reference}", bank_details["expires_at"], expire=ttl_seconds)
            except ValueError:
                logger.warning(f"Could not parse account_expires_at for {reference}: {bank_details['expires_at']}")

        payment_metadata = {
            "channel": "bank_transfer",
            "bank_transfer": bank_details,
            "bank_transfer_raw": ps_res["data"],
        }

        # 7. Save or update record
        if existing_payment:
            payment = existing_payment
            payment.transaction_id = reference
            payment.reference = reference
            payment.transaction_metadata = payment_metadata
        else:
            payment = Payment(
                order_id=order_id,
                agreement_id=agreement_id,
                buyer_id=user_id,
                seller_id=seller_id,
                amount=amount_naira,
                status="pending",
                payment_category=category,
                payment_type=payment_type,
                transaction_id=reference,
                reference=reference,
                transaction_metadata=payment_metadata,
                payment_method="paystack",
            )
            db.add(payment)

        # 8. Order-specific side effects — mirror initialize_payment, minus payment_url
        if category == "order":
            order = db.query(Order).filter(Order.id == order_id).first()
            if order:
                order.payment_reference = reference
                order.status = "processing"
                db.query(OrderItem).filter(OrderItem.order_id == order_id).update(
                    {"status": "processing"}, synchronize_session=False
                )

        db.commit()

        return {
            "account_number": bank_details["account_number"],
            "account_name": bank_details["account_name"],
            "bank_name": bank_details["bank_name"],
            "amount": amount_naira,
            "reference": reference,
            "expires_at": bank_details["expires_at"],
            "currency": "NGN",
        }

    def verify_transaction(self, db: Session, reference: str) -> Dict[str, Any]:
        """Unified verification logic"""
        ps_res = self.paystack.verify_transaction(reference)
        
        if not ps_res.get("status"):
            return ps_res

        data = ps_res.get("data", {})
        status_raw = data.get("status")

        payment = db.query(Payment).filter(Payment.transaction_id == reference).first()
        if not payment:
            return ps_res

        if status_raw == "success":
            if payment.status != "completed":
                self._handle_completion(db, payment)
            self._maybe_capture_card_mandate(db, payment, data.get("authorization") or {})
        elif status_raw in ["failed", "abandoned", "reversed"]:
            payment.status = "failed"
            db.commit()

        return ps_res

    def _maybe_capture_card_mandate(self, db: Session, payment: Payment, authorization: Dict[str, Any]) -> None:
        """When a card payment against a structured (monthly) agreement completes with
        a reusable authorization, that authorization *is* the recurring mandate - no
        separate bank-consent step needed. (Direct-debit authorizations are handled
        separately via the mandate webhook, since those aren't tied to a specific
        Payment/charge the way a card authorization is.)"""
        if not payment.agreement_id or not authorization.get("reusable"):
            return
        if authorization.get("channel") == "direct_debit":
            return

        authorization_code = authorization.get("authorization_code")
        if not authorization_code:
            return

        agreement = db.query(GeneralAgreement).filter(GeneralAgreement.id == payment.agreement_id).first()
        if not agreement or agreement.plan_type != "structured":
            return

        buyer = db.query(User).filter(User.id == payment.buyer_id).first()
        if not buyer:
            return

        mandate = db.query(PaymentMandate).filter(PaymentMandate.agreement_id == agreement.id).first()
        if not mandate:
            mandate = PaymentMandate(agreement_id=agreement.id, user_id=payment.buyer_id, email=buyer.email)
            db.add(mandate)

        mandate.email = buyer.email
        mandate.status = "active"
        mandate.authorization_code = authorization_code
        mandate.authorized_at = datetime.now(timezone.utc)
        bank = authorization.get("bank")
        mandate.bank_name = bank if isinstance(bank, str) else None
        mandate.account_number_last4 = authorization.get("last4")
        db.commit()

        create_notification(db, {
            "user_id": str(payment.buyer_id),
            "type": "agreement_update",
            "title": "Recurring Payment Authorized",
            "message": "Your card has been saved for automatic monthly installment payments.",
            "priority": "medium",
            "channels": ["in_app", "email"],
        })
        logger.info(f"Mandate {mandate.id} activated via card authorization for agreement {agreement.id}")

    def _handle_completion(self, db: Session, payment: Payment):
        """Processes logic after successful payment confirmation"""
        logger.info(f"Completing payment {payment.id} (Category: {payment.payment_category}, Amount: {payment.amount})")
        payment.status = "completed"

        # 1. Handle Order Logic
        if hasattr(payment, 'order_id') and payment.order_id:
            order = db.query(Order).filter(Order.id == payment.order_id).first()
            if order:
                order.status = "paid"

                # Sync all order items to "paid"
                db.query(OrderItem).filter(OrderItem.order_id == payment.order_id).update(
                    {"status": "paid"}, synchronize_session=False
                )

                create_notification(db, {
                    "user_id": str(payment.buyer_id),
                    "type": "payment_successful",
                    "title": "Order Payment Confirmed",
                    "message": f"Your payment of ₦{payment.amount:,.2f} for Order #{str(order.id)[:8]} has been confirmed.",
                    "priority": "high"
                })

        # 3. Handle Asset Agreement Logic
        if hasattr(payment, 'agreement_id') and payment.agreement_id:
            logger.info(f"Processing agreement payment for agreement_id: {payment.agreement_id}")
            agreement = db.query(GeneralAgreement).filter(GeneralAgreement.id == payment.agreement_id).first()
            if agreement:
                logger.info(f"Loaded agreement status: {agreement.status}, Asset Type: {agreement.asset_type}")
                gross_amount = Decimal(str(payment.amount or 0))
                if (payment.payment_type or payment.payment_category) in ["deposit", "asset_deposit"]:
                    agreement.deposit_paid = Decimal(str(agreement.deposit_paid or 0)) + gross_amount
                    agreement.remaining_balance = Decimal(str(agreement.remaining_balance or agreement.total_price)) - gross_amount

                    # If this "deposit" actually paid the full price
                    if agreement.remaining_balance <= 0:
                        agreement.status = "completed"
                        agreement.remaining_balance = Decimal("0.00")
                        logger.info(f"Agreement {agreement.id} fully paid via deposit")
                    else:
                        agreement.status = "active"

                    if agreement.inspection_id:
                        inspection = db.query(GeneralInspection).filter(GeneralInspection.id == agreement.inspection_id).first()
                        if inspection: inspection.status = "agreement_accepted"
                else:
                    agreement.remaining_balance = Decimal(str(agreement.remaining_balance or 0)) - gross_amount
                    if agreement.remaining_balance <= 0:
                        agreement.status = "completed"
                        agreement.remaining_balance = Decimal("0.00")

                # Update unit/asset status to final held state using unified logic.
                # Applies to both branches above — a one-shot full_pay or a final
                # installment payoff must flip the unit to sold just like a deposit does.
                # Note: update_unit_status's map already uses the literal "completed" to mean
                # "inspection completed" (-> inspected), so a fully-paid agreement must be
                # signaled as "paid" (-> sold) instead, to avoid colliding with that meaning.
                if agreement.status in ["active", "completed"]:
                    from core.asset_service import asset_service
                    unit_status_target = "paid" if agreement.status == "completed" else agreement.status
                    logger.info(
                        f"Payment {payment.id}: updating unit status for agreement {agreement.id} "
                        f"(asset_type={agreement.asset_type}, unit_id={agreement.unit_id}, asset_id={agreement.asset_id}, "
                        f"target={unit_status_target})"
                    )
                    try:
                        asset_service.update_unit_status(
                            db,
                            agreement.asset_type,
                            unit_status_target,
                            unit_id=agreement.unit_id,
                            asset_id=agreement.asset_id
                        )
                    except Exception:
                        # A failure here must never roll back a successful payment/agreement
                        # completion - log loudly so it's fixable, but don't re-raise.
                        logger.exception(
                            f"Payment {payment.id}: update_unit_status FAILED for agreement {agreement.id} "
                            f"(unit_id={agreement.unit_id}, asset_id={agreement.asset_id}) - unit/listing status "
                            f"may be stale and require manual correction."
                        )

                # There is no seller balance/payout concept in the single-vendor model —
                # the full payment amount is simply the business's revenue.
                if agreement.status != "completed":
                    # Update next_due_date to 1 month from now for installments
                    from datetime import timedelta
                    agreement.next_due_date = datetime.utcnow() + timedelta(days=30)

                # Send primary payment confirmation
                create_notification(db, {
                    "user_id": str(payment.buyer_id),
                    "type": "payment_successful",
                    "title": "Agreement Payment Confirmed",
                    "message": f"Your payment of ₦{payment.amount:,.2f} for your {agreement.asset_type} agreement has been confirmed. Next payment due on {agreement.next_due_date.strftime('%B %d, %Y') if agreement.next_due_date else 'N/A'}.",
                    "priority": "high"
                })

                # Ownership logic (individual customer purchase)
                if agreement.status == "completed" and agreement.asset_type == "property" and agreement.unit_id:
                    unit = db.query(PropertyUnit).filter(PropertyUnit.id == agreement.unit_id).first()
                    if unit:
                        # Set to sold or rented based on parent property listing_type
                        parent = db.query(Property).filter(Property.id == agreement.asset_id).first()
                        if parent and parent.listing_type == "rental":
                            unit.status = "rented"
                        else:
                            unit.status = "sold"
                        # If all units are sold, mark property as sold? 
                        # (Optional logic but maybe good for UX)

                # Special "Ownership" notification if agreement is now fully paid
                if agreement.status == "completed":
                    asset_noun = "Property" if agreement.asset_type == "property" else ("Car" if agreement.asset_type == "automotive" else "Phone")
                    create_notification(db, {
                        "user_id": str(payment.buyer_id),
                        "type": "agreement_completed",
                        "title": f"🎉 Congratulations! You now own this {asset_noun}!",
                        "message": f"Your {agreement.asset_type} agreement has been fully paid. You are now the full owner of this asset. Thank you for choosing LEL Store!",
                        "priority": "urgent",
                        "channels": ["in_app", "email"]
                    })

        db.commit()
        
    def handle_mandate_webhook(self, db: Session, event: str, reference: str, authorization: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """Process a direct-debit `authorization` payload from a Paystack webhook that
        concerns mandate lifecycle (authorization consent, revocation) rather than a
        specific Payment. Returns None if `reference` doesn't belong to a mandate at
        all (e.g. it's actually a regular recurring installment charge, which has its
        own Payment row and should fall through to the normal Payment-based handling).

        NOTE: the exact webhook event name(s) Paystack fires for mandate
        authorization/revocation could not be confirmed against live docs while
        building this - this handles it defensively off the `authorization` object's
        `channel`/`reusable`/`authorization_code` fields, which should be stable
        regardless of the wrapping event name, but re-verify against a real Paystack
        webhook log before relying on this in production.
        """
        mandate = db.query(PaymentMandate).filter(PaymentMandate.reference == reference).first()

        is_revocation = "revoked" in (event or "").lower() or authorization.get("reusable") is False
        if not mandate and is_revocation:
            authorization_code = authorization.get("authorization_code")
            if authorization_code:
                mandate = db.query(PaymentMandate).filter(PaymentMandate.authorization_code == authorization_code).first()

        if not mandate:
            return None

        if is_revocation:
            mandate.status = "revoked"
            db.commit()
            create_notification(db, {
                "user_id": str(mandate.user_id),
                "type": "agreement_update",
                "title": "Recurring Payment Cancelled",
                "message": "Your bank has cancelled the recurring debit authorization for your monthly payment plan. Please re-authorize to avoid missing installments.",
                "priority": "urgent",
                "channels": ["in_app", "email"],
            })
            logger.info(f"Mandate {mandate.id} revoked via webhook")
            return {"status": "success"}

        authorization_code = authorization.get("authorization_code")
        if authorization_code and authorization.get("reusable"):
            mandate.authorization_code = authorization_code
            mandate.status = "active"
            mandate.authorized_at = datetime.now(timezone.utc)
            bank = authorization.get("bank")
            mandate.bank_name = bank if isinstance(bank, str) else (authorization.get("bank_name") or None)
            last4 = authorization.get("last4") or authorization.get("account_number", "")[-4:] if authorization.get("account_number") else None
            mandate.account_number_last4 = last4
            db.commit()

            create_notification(db, {
                "user_id": str(mandate.user_id),
                "type": "agreement_update",
                "title": "Recurring Payment Authorized",
                "message": "Your bank account has been authorized for recurring monthly debits. We'll automatically charge your installment each month.",
                "priority": "medium",
                "channels": ["in_app", "email"],
            })
            logger.info(f"Mandate {mandate.id} activated via webhook")
            return {"status": "success"}

        logger.info(f"Ignoring non-actionable mandate webhook for reference {reference} (event={event})")
        return {"status": "ignored", "reason": "mandate_not_actionable"}

    def charge_mandate_installment(self, db: Session, agreement: GeneralAgreement, mandate: PaymentMandate) -> Payment:
        """Attempt one recurring installment charge against an active Direct Debit
        mandate (called by the daily `charge_due_mandates` celery task). Creates a
        Payment row; if Paystack responds synchronously with success, completes it
        immediately via the normal completion path. A pending/async response is left
        for the `charge.success`/`charge.failed` webhook to resolve later."""
        amount = Decimal(str(agreement.monthly_installment or 0))
        if amount <= 0:
            raise ValueError(f"Agreement {agreement.id} has no monthly_installment configured")

        reference = f"LEL_{uuid.uuid4().hex[:10].upper()}"
        payment = Payment(
            agreement_id=agreement.id,
            buyer_id=agreement.user_id,
            seller_id=agreement.seller_id,
            amount=amount,
            status="pending",
            payment_category="asset_installment",
            payment_type="installment",
            transaction_id=reference,
            reference=reference,
            payment_method="paystack",
        )
        db.add(payment)
        db.commit()

        try:
            ps_res = self.paystack.charge_authorization(
                authorization_code=mandate.authorization_code,
                email=mandate.email,
                amount=int(amount * 100),
                reference=reference,
            )
        except Exception as e:
            logger.error(f"Mandate charge failed to reach Paystack for agreement {agreement.id}: {e}")
            payment.status = "failed"
            mandate.failed_attempts = (mandate.failed_attempts or 0) + 1
            db.commit()
            return payment

        ps_status = (ps_res.get("data") or {}).get("status")
        if ps_res.get("status") and ps_status == "success":
            self._handle_completion(db, payment)
            mandate.failed_attempts = 0
            db.commit()
        elif ps_status in ["failed", "abandoned", "reversed"]:
            payment.status = "failed"
            mandate.failed_attempts = (mandate.failed_attempts or 0) + 1
            db.commit()
        # else: pending/processing - the charge.success/charge.failed webhook resolves it later.

        return payment

    def refund_payment(
        self,
        db: Session,
        payment_id: str,
        admin_id: str,
        reason: str = "Requested by admin/buyer"
    ) -> Payment:
        """Process a refund via Paystack and update local records"""
        payment = db.query(Payment).filter(Payment.id == payment_id).first()
        
        if not payment:
            raise HTTPException(status_code=404, detail="Payment not found")
            
        if payment.status != "completed":
            raise HTTPException(status_code=400, detail=f"Cannot refund a payment with status '{payment.status}'")
            
        if payment.payment_method != "paystack":
            raise HTTPException(status_code=400, detail="Only Paystack payments can be refunded via API")
            
        # Call Paystack refund
        try:
            refund_res = self.paystack.initiate_refund(
                reference=payment.reference,
                customer_note=reason
            )
            
            if refund_res.get("status"):
                payment.status = "refunded"
                payment.transaction_metadata = {**(payment.transaction_metadata or {}), "refund_reason": reason, "refunded_by": str(admin_id), "refund_data": refund_res.get("data")}
                
                # Notify Buyer
                create_notification(db, {
                    "user_id": str(payment.buyer_id),
                    "type": "payment_successful", # fallback
                    "title": "Payment Refunded",
                    "message": f"Your payment of ₦{payment.amount:,.2f} has been refunded. Reason: {reason}",
                    "channels": ["in_app", "email"]
                })
                
                db.commit()
                logger.info(f"Payment {payment_id} refunded successfully.")
                return payment
            else:
                raise HTTPException(status_code=400, detail=refund_res.get("message", "Refund failed"))
                
        except Exception as e:
            db.rollback()
            logger.error(f"Error refunding payment {payment_id}: {str(e)}")
            raise HTTPException(status_code=500, detail=f"Refund failed: {str(e)}")

payment_service = PaymentService()
