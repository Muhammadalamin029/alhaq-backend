from sqlalchemy.orm import Session
from typing import Optional, Dict, Any
from decimal import Decimal
import functools
import uuid
import logging
from datetime import datetime, timezone
from fastapi import HTTPException

from core.model import (
    Payment, Order, OrderItem, GeneralAgreement,
    GeneralInspection, Property, PropertyUnit, PaymentMandate, User
)
from core.flutterwave_service import flutterwave_service
from core.receipt_service import derive_receipt_number
from core.notifications_service import create_notification
from core.email_service import _ref
from core.redis_client import redis_client
from core.system_settings_service import system_settings_service
from core.order_installment_service import order_installment_service

logger = logging.getLogger(__name__)

BANK_TRANSFER_EXPIRY_PREFIX = "bank_transfer_expiry:"
BANK_TRANSFER_INIT_LOCK_PREFIX = "bank_transfer_init_lock:"
CARD_CHARGE_INIT_LOCK_PREFIX = "card_charge_init_lock:"
# How long a duplicate initiation is held off while the winner finishes.
INIT_LOCK_TTL_SECONDS = 30


def _serialize_initiation(prefix: str, busy_message: str):
    """Decorator serializing concurrent initiations for the same payment target.

    The decorated method must receive ``category``/``order_id``/``agreement_id``
    as keyword arguments (all current callers do). The loser gets HTTP 429 and
    its retry lands on the reuse path (or a fresh attempt). The lock is always
    released in ``finally``; TTL only bounds stale holds after a crash.
    """
    def decorator(fn):
        @functools.wraps(fn)
        def wrapper(self, db, user_id, *args, **kwargs):
            category = kwargs.get("category")
            order_id = kwargs.get("order_id")
            agreement_id = kwargs.get("agreement_id")
            lock_key = f"{prefix}{user_id}:{category}:{order_id or agreement_id}"
            token = redis_client.acquire_lock(lock_key, expire=INIT_LOCK_TTL_SECONDS)
            if not token:
                raise HTTPException(status_code=429, detail=busy_message)
            try:
                return fn(self, db, user_id, *args, **kwargs)
            finally:
                redis_client.release_lock(lock_key, token)
        return wrapper
    return decorator


def _safe_notify(db: Session, payload: Dict[str, Any]):
    """Best-effort notification that can never break payment completion.

    A notification failure (e.g. a type missing from the DB enum) must never
    turn a successful Flutterwave charge into a 500 / lost payment state.
    Core payment/agreement state is committed by the caller BEFORE
    notifications, so a rollback here only drops the notification itself.
    """
    try:
        return create_notification(db, payload)
    except Exception:
        logger.exception(
            f"Non-fatal: failed to create '{payload.get('type')}' "
            f"notification for user {payload.get('user_id')}"
        )
        try:
            db.rollback()
        except Exception:
            pass
        return None


def _notify_admins_of_payment(
    db: Session,
    payment,
    target_label: str,
    data: Dict[str, Any],
):
    """Best-effort admin alert for received money (honors System Alerts pref).

    Never breaks completion: notify_admins itself guards on preferences, and
    any unexpected failure is swallowed here like _safe_notify.
    """
    try:
        buyer = db.query(User).filter(User.id == payment.buyer_id).first()
        payer_label = buyer.email if buyer else f"buyer {str(payment.buyer_id)[:8]}"
        amount = Decimal(str(payment.amount or 0))
        channel_label = (payment.payment_method or "flutterwave").replace("_", " ").title()
        system_settings_service.notify_admins(
            db=db,
            event_key="system_alert",
            title=f"Payment Received — ₦{amount:,.2f}",
            message=(
                f"{channel_label} payment of ₦{amount:,.2f} "
                f"received for {target_label} from {payer_label}."
            ),
            data=data,
            priority="medium",
        )
    except Exception:
        logger.exception("Non-fatal: failed to notify admins of payment")
        try:
            db.rollback()
        except Exception:
            pass


class PaymentService:
    PROVIDER = "flutterwave"

    def __init__(self):
        self.flw = flutterwave_service

    @staticmethod
    def _validate_card_fields(card_number: str, cvv: str, expiry_month: str, expiry_year: str) -> str:
        """Light server-side card sanity check. Returns normalized PAN digits."""
        digits = "".join(ch for ch in (card_number or "") if ch.isdigit())
        if not (13 <= len(digits) <= 19):
            raise HTTPException(status_code=400, detail="Invalid card number")
        if not ((cvv or "").isdigit() and 3 <= len(cvv) <= 4):
            raise HTTPException(status_code=400, detail="Invalid CVV")
        try:
            month = int(expiry_month)
        except (TypeError, ValueError):
            raise HTTPException(status_code=400, detail="Invalid expiry month")
        if not 1 <= month <= 12:
            raise HTTPException(status_code=400, detail="Invalid expiry month")
        year = (expiry_year or "").strip()
        if len(year) == 4 and year.isdigit():
            year = year[2:]
        if not (len(year) == 2 and year.isdigit()):
            raise HTTPException(status_code=400, detail="Invalid expiry year")
        return digits

    def _validate_payment_category(self, category: str, order_id: Optional[str], agreement_id: Optional[str]) -> None:
        if category == "order" and not order_id:
            raise HTTPException(status_code=400, detail="order_id is required for order payments")
        if category in ["asset_deposit", "asset_installment", "full_pay"] and not agreement_id:
            raise HTTPException(status_code=400, detail="agreement_id is required for asset payments")

    @staticmethod
    def _infer_payment_type(category: str, metadata: Optional[Dict]) -> Optional[str]:
        payment_type = (metadata or {}).get("payment_type")
        if payment_type:
            return payment_type
        if category == "asset_deposit":
            return "deposit"
        if category == "asset_installment":
            return "installment"
        if category == "order":
            return "order"
        if category == "full_pay":
            return "full_pay"
        return None

    def _prepare_payment(
        self,
        db: Session,
        user_id: str,
        category: str,
        amount_naira: Decimal,
        order_id: Optional[str] = None,
        agreement_id: Optional[str] = None,
        metadata: Optional[Dict] = None,
    ):
        """Shared validation + pending-payment staging for card and bank-transfer charges.

        Returns ``(payment, agreement)`` where ``payment`` is a pending ``Payment``
        row (reused or newly created) with a fresh ``LEL_`` tx_ref already assigned
        to ``transaction_id``/``reference``. The caller still must invoke the
        provider, attach provider ids to ``transaction_metadata``, and commit.
        Amounts here are **Naira major units** (Flutterwave convention).
        """
        self._validate_payment_category(category, order_id, agreement_id)

        existing_payment = db.query(Payment).filter(
            Payment.buyer_id == user_id,
            Payment.status == "pending",
            Payment.payment_category == category
        )
        if order_id:
            existing_payment = existing_payment.filter(Payment.order_id == order_id)
        if agreement_id:
            existing_payment = existing_payment.filter(Payment.agreement_id == agreement_id)
        existing_payment = existing_payment.first()

        payment_type = self._infer_payment_type(category, metadata)

        seller_id = None
        agreement = None
        if agreement_id:
            agreement = db.query(GeneralAgreement).filter(GeneralAgreement.id == agreement_id).first()
            if agreement:
                seller_id = agreement.seller_id

        # Admin-configured minimum initial-payment percentage for installment plans.
        # Checked once - only on the payment that starts the plan (no prior completed
        # payment on this agreement yet) - never on later top-up installments.
        if agreement and agreement.payment_plan == "installment" and category in ("asset_deposit", "asset_installment"):
            has_prior_payment = db.query(Payment).filter(
                Payment.agreement_id == agreement_id,
                Payment.status == "completed"
            ).first() is not None
            if not has_prior_payment:
                min_percent = Decimal(str(system_settings_service.get_payment_setting_values(db).get("installment_min_percent", 0)))
                paid_percent = (amount_naira / agreement.total_price * 100) if agreement.total_price else Decimal(0)
                if paid_percent < min_percent:
                    raise HTTPException(
                        status_code=400,
                        detail=f"An initial payment of at least {min_percent}% of the price is required to start an installment plan."
                    )

        # Product-order installment validation (first payment percentage, balance cap, etc.)
        if category == "order" and (metadata or {}).get("payment_type") == "installment":
            order = db.query(Order).filter(Order.id == order_id).first()
            order_installment_service.validate_installment_payment(db, user_id, order, amount_naira)

        reference = f"LEL_{uuid.uuid4().hex[:10].upper()}"

        if existing_payment:
            logger.info(f"Re-using existing pending payment for {category}: {existing_payment.id}")
            payment = existing_payment
            payment.amount = amount_naira
            if (metadata or {}).get("payment_type"):
                payment.payment_type = payment_type
            payment.transaction_id = reference
            payment.reference = reference
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
                payment_method=self.PROVIDER
            )
            db.add(payment)
            db.flush()
            payment.receipt_number = derive_receipt_number(payment)

        return payment, agreement

    def _mark_order_processing(self, db: Session, order_id: Optional[str], reference: str) -> None:
        if not order_id:
            return
        order = db.query(Order).filter(Order.id == order_id).first()
        if order:
            order.payment_reference = reference
            order.status = "processing"
            db.query(OrderItem).filter(OrderItem.order_id == order_id).update(
                {"status": "processing"}, synchronize_session=False
            )

    def _provider_meta(self, user_id: str, category: str, order_id: Optional[str], agreement_id: Optional[str], metadata: Optional[Dict]) -> Dict[str, Any]:
        return {
            "user_id": str(user_id),
            "category": category,
            "order_id": str(order_id) if order_id else None,
            "agreement_id": str(agreement_id) if agreement_id else None,
            **(metadata or {})
        }

    def _store_provider_ids(self, payment: Payment, flw_data: Dict[str, Any], channel: str) -> None:
        provider_meta = dict(payment.transaction_metadata or {})
        provider_meta.update({
            "provider": self.PROVIDER,
            "channel": channel,
            "flw_ref": flw_data.get("flw_ref"),
            "flw_id": flw_data.get("id"),
        })
        payment.transaction_metadata = provider_meta

    # ── Direct card charge (multi-step) ────────────────────────
    @_serialize_initiation(CARD_CHARGE_INIT_LOCK_PREFIX, "A card payment is already being processed. Please wait a moment and try again.")
    def charge_card_payment(
        self,
        db: Session,
        user_id: str,
        email: str,
        amount_naira: Decimal,
        category: str,
        card_number: str,
        cvv: str,
        expiry_month: str,
        expiry_year: str,
        order_id: Optional[str] = None,
        agreement_id: Optional[str] = None,
        fullname: Optional[str] = None,
        phone_number: Optional[str] = None,
        redirect_url: Optional[str] = None,
        metadata: Optional[Dict] = None,
        payment_method: str = "flutterwave"
    ) -> Dict[str, Any]:
        """Step 1 of the Direct-API card flow: charge the card, return the next step.

        Raw card fields are passed straight through to Flutterwave over TLS and
        are never persisted. Response: ``next_step`` of pin | avs | otp |
        redirect | success | failed plus ``tx_ref`` for the follow-up calls.
        """
        if payment_method != self.PROVIDER:
            raise HTTPException(status_code=400, detail="Manual payments have been removed. Please use card payment.")

        pan = self._validate_card_fields(card_number, cvv, expiry_month, expiry_year)

        payment, _agreement = self._prepare_payment(
            db, user_id, category, amount_naira, order_id, agreement_id, metadata
        )
        tx_ref = payment.reference

        flw_res = self.flw.charge_card(
            card_number=pan,
            cvv=cvv,
            expiry_month=str(expiry_month).zfill(2),
            expiry_year=expiry_year[-2:],
            amount=float(amount_naira),
            email=email,
            tx_ref=tx_ref,
            fullname=fullname,
            phone_number=phone_number,
            redirect_url=redirect_url,
            meta=self._provider_meta(user_id, category, order_id, agreement_id, metadata),
        )
        if not flw_res.get("status"):
            raise HTTPException(status_code=400, detail=flw_res.get("message", "Card charge failed"))

        flw_data = flw_res.get("data") or {}
        if not flw_data.get("id") and not flw_data.get("flw_ref"):
            # Fail closed: Flutterwave returned no charge object (null data).
            # Advancing would strand the user on a PIN/OTP screen whose
            # follow-up calls can never succeed (no flw_ref/tx_ref to act on).
            logger.error(
                f"Flutterwave card charge for {tx_ref} returned no charge data: "
                f"status={flw_res.get('status')!r} message={flw_res.get('message')!r}"
            )
            raise HTTPException(
                status_code=400,
                detail=flw_res.get("message") or "Card charge failed: no charge created. Please check your card details or try another card.",
            )
        self._store_provider_ids(payment, flw_data, channel="card")
        self._mark_order_processing(db, order_id, tx_ref)
        db.commit()

        step = self.flw.next_step(flw_res)
        # Our reference is the source of truth for authorize/validate lookups —
        # never trust the provider echo (it may be missing or rewritten).
        step["tx_ref"] = tx_ref
        step["payment_id"] = str(payment.id)
        if step.get("next_step") == "success":
            self.verify_transaction(db, tx_ref, transaction_id=flw_data.get("id"))
            step["next_step"] = "success"
        return step

    def authorize_card_payment(
        self,
        db: Session,
        tx_ref: str,
        card_number: str,
        cvv: str,
        expiry_month: str,
        expiry_year: str,
        authorization: Dict[str, Any],
        email: Optional[str] = None,
        fullname: Optional[str] = None,
        phone_number: Optional[str] = None,
        redirect_url: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Step 2: resend the charge with PIN/AVS authorization.

        Flutterwave requires the full card payload on re-charge, so the client
        resubmits the card fields together with ``authorization``. Card data is
        never stored server-side.
        """
        payment = db.query(Payment).filter(Payment.reference == tx_ref).first()
        if not payment:
            logger.warning(f"Card authorize for unknown tx_ref={tx_ref} (client session likely stale or remounted)")
            raise HTTPException(status_code=404, detail="Payment not found")
        if payment.status != "pending":
            logger.warning(f"Card authorize for non-pending payment tx_ref={tx_ref} status={payment.status}")
            raise HTTPException(status_code=400, detail=f"Payment is already {payment.status}")

        pan = self._validate_card_fields(card_number, cvv, expiry_month, expiry_year)
        mode = (authorization or {}).get("mode")
        if mode not in ("pin", "avs_noauth", "avs"):
            raise HTTPException(status_code=400, detail="authorization.mode must be pin or avs_noauth")

        flw_res = self.flw.charge_card(
            card_number=pan,
            cvv=cvv,
            expiry_month=str(expiry_month).zfill(2),
            expiry_year=str(expiry_year)[-2:],
            amount=float(payment.amount),
            email=email or self._payment_email(db, payment),
            tx_ref=tx_ref,
            fullname=fullname,
            phone_number=phone_number,
            redirect_url=redirect_url,
            authorization=authorization,
            meta=(payment.transaction_metadata or {}),
        )
        if not flw_res.get("status"):
            raise HTTPException(status_code=400, detail=flw_res.get("message", "Card authorization failed"))

        flw_data = flw_res.get("data") or {}
        if not flw_data.get("id") and not flw_data.get("flw_ref"):
            # Fail closed (same rationale as charge step): no charge object
            # means the follow-up OTP/redirect calls can never succeed.
            logger.error(
                f"Flutterwave card authorize for {tx_ref} returned no charge data: "
                f"status={flw_res.get('status')!r} message={flw_res.get('message')!r}"
            )
            raise HTTPException(
                status_code=400,
                detail=flw_res.get("message") or "Card authorization failed: no charge created. Please try again.",
            )
        self._store_provider_ids(payment, flw_data, channel="card")
        db.commit()

        step = self.flw.next_step(flw_res)
        step["tx_ref"] = tx_ref
        step["payment_id"] = str(payment.id)
        if step.get("next_step") == "success":
            self.verify_transaction(db, tx_ref, transaction_id=flw_data.get("id"))
            step["next_step"] = "success"
        return step

    def validate_card_payment(self, db: Session, tx_ref: str, otp: str) -> Dict[str, Any]:
        """Step 3: validate the charge with the OTP sent to the customer."""
        payment = db.query(Payment).filter(Payment.reference == tx_ref).first()
        if not payment:
            logger.warning(f"Card validate for unknown tx_ref={tx_ref} (client session likely stale or remounted)")
            raise HTTPException(status_code=404, detail="Payment not found")
        if payment.status != "pending":
            logger.warning(f"Card validate for non-pending payment tx_ref={tx_ref} status={payment.status}")
            raise HTTPException(status_code=400, detail=f"Payment is already {payment.status}")
        flw_ref = (payment.transaction_metadata or {}).get("flw_ref")
        if not flw_ref:
            raise HTTPException(status_code=400, detail="No Flutterwave charge found for this payment")

        flw_res = self.flw.validate_charge(otp=otp, flw_ref=flw_ref)
        if not flw_res.get("status"):
            raise HTTPException(status_code=400, detail=flw_res.get("message", "OTP validation failed"))

        flw_data = flw_res.get("data") or {}
        self._store_provider_ids(payment, flw_data, channel="card")
        db.commit()

        result = self.verify_transaction(db, tx_ref, transaction_id=flw_data.get("id"))
        return {"next_step": "success" if result.get("completed") else "pending",
                "tx_ref": tx_ref, "payment_id": str(payment.id), "verification": result}

    def _payment_email(self, db: Session, payment: Payment) -> str:
        buyer = db.query(User).filter(User.id == payment.buyer_id).first()
        return (buyer.email if buyer else "") or "customer@example.com"

    def _normalize_bank_transfer_details(self, flw_response: Dict[str, Any]) -> Dict[str, Optional[str]]:
        """Extract display fields from a Flutterwave bank-transfer charge response."""
        return flutterwave_service.normalize_bank_transfer_details(flw_response)

    @_serialize_initiation(BANK_TRANSFER_INIT_LOCK_PREFIX, "A bank transfer is already being generated. Please wait a moment and try again.")
    def initialize_bank_transfer_payment(
        self,
        db: Session,
        user_id: str,
        email: str,
        amount_naira: Decimal,
        category: str,
        order_id: Optional[str] = None,
        agreement_id: Optional[str] = None,
        metadata: Optional[Dict] = None,
        fullname: Optional[str] = None,
        phone_number: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Generate a one-time 'Pay with Transfer' account number for an order or agreement payment.

        Amounts are **Naira major units**. Reuses a still-valid account for the
        same pending payment instead of minting a new one per call.
        """
        self._validate_payment_category(category, order_id, agreement_id)

        # Reuse existing bank transfer details if still valid for this amount
        existing_payment = db.query(Payment).filter(
            Payment.buyer_id == user_id,
            Payment.status == "pending",
            Payment.payment_category == category
        )
        if order_id:
            existing_payment = existing_payment.filter(Payment.order_id == order_id)
        if agreement_id:
            existing_payment = existing_payment.filter(Payment.agreement_id == agreement_id)
        existing_payment = existing_payment.first()
        requested_payment_type = (metadata or {}).get("payment_type")

        # 2a. Product-order installment validation (first payment percentage, balance cap, etc.)
        if category == "order" and requested_payment_type == "installment":
            order = db.query(Order).filter(Order.id == order_id).first()
            order_installment_service.validate_installment_payment(
                db, user_id, order, amount_naira
            )

        # 2b. Reuse existing bank transfer details only if the account is still
        # valid for this amount: Redis TTL key alive AND the stored expires_at
        # still in the future. Otherwise fall through and mint a fresh account
        # (a stale cached timestamp is what used to blank the UI with an
        # instant "expired" screen).
        if existing_payment and existing_payment.transaction_metadata:
            cached = existing_payment.transaction_metadata
            cached_bank_transfer = cached.get("bank_transfer") if cached.get("channel") == "bank_transfer" else None
            if cached_bank_transfer and cached_bank_transfer.get("account_number") and existing_payment.amount == amount_naira:
                redis_alive = redis_client.exists(f"{BANK_TRANSFER_EXPIRY_PREFIX}{existing_payment.reference}")
                cached_expiry = cached_bank_transfer.get("expires_at")

                if not redis_alive or not self.flw.expiry_is_fresh(cached_expiry):
                    logger.info(
                        f"Cached bank transfer for {category} {existing_payment.id} is stale "
                        f"(redis_alive={redis_alive}, expires_at={cached_expiry}); minting a fresh account."
                    )
                else:
                    if requested_payment_type and existing_payment.payment_type != requested_payment_type:
                        existing_payment.payment_type = requested_payment_type
                        db.commit()
                    logger.info(f"Reusing existing bank transfer account for {category}: {existing_payment.id}")
                    return {
                        "account_number": cached_bank_transfer["account_number"],
                        "account_name": cached_bank_transfer.get("account_name", ""),
                        "bank_name": cached_bank_transfer.get("bank_name", ""),
                        "amount": amount_naira,
                        "reference": existing_payment.reference,
                        # Re-normalize so the client always gets ISO+offset, even
                        # for rows cached before the normalization change.
                        "expires_at": self.flw.normalize_expiry_iso(cached_expiry),
                        "currency": "NGN",
                    }

        # 3. Infer payment_type if missing in metadata
        payment_type = self._infer_payment_type(category, metadata)

        # Get seller_id if applicable
        seller_id = None
        if agreement_id:
            agreement = db.query(GeneralAgreement).filter(GeneralAgreement.id == agreement_id).first()
            if agreement:
                seller_id = agreement.seller_id

        if existing_payment:
            logger.info(f"Re-using existing pending payment for {category}: {existing_payment.id}")
            existing_payment.amount = amount_naira
            if requested_payment_type:
                existing_payment.payment_type = payment_type

        # 4. Generate unique reference
        reference = f"LEL_{uuid.uuid4().hex[:10].upper()}"

        # 5. Prepare metadata for Flutterwave
        flw_meta = self._provider_meta(user_id, category, order_id, agreement_id, metadata)

        # 6. Initiate the Pay with Transfer charge
        flw_res = self.flw.charge_bank_transfer(
            email=email,
            amount=float(amount_naira),
            tx_ref=reference,
            fullname=fullname,
            phone_number=phone_number,
            meta=flw_meta,
        )

        if not flw_res.get("status"):
            raise HTTPException(status_code=400, detail=flw_res.get("message", "Flutterwave bank transfer initialization failed"))

        bank_details = self._normalize_bank_transfer_details(flw_res)
        if not bank_details["account_number"]:
            logger.error(f"Bank transfer charge for {reference} returned no account number: { {k: v for k, v in flw_res.items() if k != 'meta'} }")
            raise HTTPException(status_code=502, detail="Bank transfer details unavailable from Flutterwave")

        if bank_details["expires_at"]:
            try:
                expiry_dt = datetime.fromisoformat(str(bank_details["expires_at"]).replace("Z", "+00:00"))
                if expiry_dt.tzinfo is None:
                    expiry_dt = expiry_dt.replace(tzinfo=timezone.utc)
                remaining = (expiry_dt - datetime.now(timezone.utc)).total_seconds()
                if remaining <= 0:
                    logger.error(
                        f"Flutterwave returned a past account_expiration for {reference}: "
                        f"{bank_details['expires_at']} (backend clock may be skewed)"
                    )
                ttl_seconds = max(30, int(remaining))
                redis_client.set(f"{BANK_TRANSFER_EXPIRY_PREFIX}{reference}", bank_details["expires_at"], expire=ttl_seconds)
            except ValueError:
                logger.warning(f"Could not parse account_expiration for {reference}: {bank_details['expires_at']}")

        flw_data = flw_res.get("data") or {}
        payment_metadata = {
            "provider": self.PROVIDER,
            "channel": "bank_transfer",
            "bank_transfer": bank_details,
            "flw_ref": flw_data.get("flw_ref"),
            "flw_id": flw_data.get("id"),
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
                payment_method=self.PROVIDER,
            )
            db.add(payment)
            db.flush()
            payment.receipt_number = derive_receipt_number(payment)

        # 8. Order-specific side effects
        self._mark_order_processing(db, order_id, reference)

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

    def verify_transaction(self, db: Session, tx_ref: str, transaction_id: Optional[int] = None) -> Dict[str, Any]:
        """Unified verification logic against Flutterwave.

        Resolves the Flutterwave transaction id from the argument, the stored
        payment metadata, or a ``verify_by_reference`` lookup — then requires
        ``status == successful`` plus matching amount/currency/tx_ref before
        completing the payment. Returns the raw FLW response plus a
        ``completed`` flag for convenience.
        """
        payment = db.query(Payment).filter(
            (Payment.reference == tx_ref) | (Payment.transaction_id == tx_ref)
        ).first()

        flw_id = transaction_id or ((payment.transaction_metadata or {}).get("flw_id") if payment else None)
        if flw_id is None and payment is not None:
            try:
                lookup = self.flw.verify_by_tx_ref(tx_ref)
                flw_id = (lookup.get("data") or {}).get("id")
            except Exception as e:
                logger.error(f"Flutterwave tx_ref lookup failed for {tx_ref}: {e}")

        if flw_id is None:
            return {"status": "error", "message": "Could not resolve Flutterwave transaction", "completed": False}

        try:
            flw_res = self.flw.verify_transaction(int(flw_id))
        except Exception as e:
            logger.error(f"Flutterwave verification error for {tx_ref}: {e}")
            return {"status": "error", "message": str(e), "completed": False}

        if not flw_res.get("status"):
            return {**flw_res, "completed": False}

        data = flw_res.get("data", {})
        status_raw = str(data.get("status") or "").lower()

        if not payment:
            return {**flw_res, "completed": False}

        # Failsafe: the webhook/redirect payload must agree with the ledger.
        expected_amount = float(payment.amount or 0)
        try:
            flw_amount = float(data.get("amount") or 0)
        except (TypeError, ValueError):
            flw_amount = -1
        matches = (
            (data.get("tx_ref") in (payment.reference, payment.transaction_id))
            and abs(flw_amount - expected_amount) < 0.01
            and str(data.get("currency") or "NGN").upper() == "NGN"
        )
        if not matches:
            logger.error(
                f"Flutterwave verification mismatch for {tx_ref}: "
                f"expected NGN {expected_amount}, got {data.get('currency')} {data.get('amount')} / {data.get('tx_ref')}"
            )
            return {**flw_res, "completed": False}

        self._store_provider_ids(payment, data, channel=(payment.transaction_metadata or {}).get("channel", "card"))

        if status_raw == "successful":
            if payment.status != "completed":
                self._handle_completion(db, payment)
            self._maybe_capture_card_mandate(db, payment, data)
            db.commit()
            return {**flw_res, "completed": True}
        elif status_raw in ["failed", "cancelled", "expired"]:
            payment.status = "failed"
            db.commit()

        return {**flw_res, "completed": False}

    def _maybe_capture_card_mandate(self, db: Session, payment: Payment, flw_data: Dict[str, Any]) -> None:
        """When a card payment against a structured (monthly) agreement completes and
        Flutterwave returns a reusable card ``token``, that token *is* the recurring
        mandate — later installments are charged via ``/v3/tokenized-charges`` with
        the same customer email. No separate bank-consent step is needed."""
        if not payment.agreement_id:
            return

        token = self.flw.extract_card_token(flw_data)
        if not token:
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

        card = flw_data.get("card") or {}
        mandate.email = buyer.email
        mandate.status = "active"
        mandate.authorization_code = token
        mandate.authorized_at = datetime.now(timezone.utc)
        mandate.bank_name = card.get("issuer") or None
        last4 = card.get("last_4digits") or card.get("last4")
        mandate.account_number_last4 = last4
        db.commit()

        _safe_notify(db, {
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
                if (payment.payment_type or "") == "installment":
                    # Flush so the derived summary sees this payment as completed,
                    # then recompute the balance from the ledger rather than counters.
                    db.flush()
                    db.expire(order, ["payments"])
                    summary = order_installment_service.summarize(db, order)
                    amount_paid = summary["amount_paid"]
                    remaining = summary["remaining_balance"]
                    total_amount = float(order.total_amount or 0)
                    notification_data = {
                        "payment_id": str(payment.id),
                        "order_id": str(order.id),
                        "amount": float(payment.amount or 0),
                        "amount_paid": amount_paid,
                        "remaining_balance": remaining,
                        "total_amount": total_amount,
                    }

                    if remaining <= 0:
                        order.status = "paid"
                        # Sync all order items to "paid"
                        db.query(OrderItem).filter(OrderItem.order_id == payment.order_id).update(
                            {"status": "paid"}, synchronize_session=False
                        )
                        create_notification(db, {
                            "user_id": str(payment.buyer_id),
                            "type": "payment_successful",
                            "title": "Order Payment Confirmed",
                            "message": (
                                f"Your final installment payment of ₦{payment.amount:,.2f} for "
                                f"Order #{str(order.id)[:8]} has been confirmed. Your order is fully paid."
                            ),
                            "priority": "high",
                            "channels": ["in_app", "email"],
                            "data": {
                                **notification_data,
                                "context": "order",
                                "reference": payment.reference,
                            },
                        })
                        _notify_admins_of_payment(
                            db, payment,
                            f"Order #{str(order.id)[:8].upper()} (final installment)",
                            {"payment_id": str(payment.id),
                             "order_id": str(order.id),
                             "amount": float(payment.amount or 0)},
                        )
                    else:
                        # Order stays processing while a balance remains.
                        order.status = "processing"
                        create_notification(db, {
                            "user_id": str(payment.buyer_id),
                            "type": "installment_paid",
                            "title": "Installment Payment Received",
                            "message": (
                                f"Your installment payment of ₦{payment.amount:,.2f} for "
                                f"Order #{str(order.id)[:8]} has been confirmed. "
                                f"Remaining balance: ₦{remaining:,.2f}."
                            ),
                            "priority": "high",
                            "channels": ["in_app", "email"],
                            "data": {
                                **notification_data,
                                "context": "installment",
                                "reference": payment.reference,
                            },
                        })
                        _notify_admins_of_payment(
                            db, payment,
                            f"Order #{str(order.id)[:8].upper()} (installment)",
                            {"payment_id": str(payment.id),
                             "order_id": str(order.id),
                             "amount": float(payment.amount or 0)},
                        )
                else:
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
                        "priority": "high",
                        "channels": ["in_app", "email"],
                        "data": {
                            "context": "order",
                            "payment_id": str(payment.id),
                            "order_id": str(order.id),
                            "reference": payment.reference,
                            "amount": float(payment.amount or 0),
                            "amount_paid": float(payment.amount or 0),
                            "remaining_balance": 0,
                            "total_amount": float(order.total_amount or 0),
                        },
                    })
                    _notify_admins_of_payment(
                        db, payment,
                        f"Order #{str(order.id)[:8].upper()}",
                        {"payment_id": str(payment.id),
                         "order_id": str(order.id),
                         "amount": float(payment.amount or 0)},
                    )

        # 3. Handle Asset Agreement Logic
        if hasattr(payment, 'agreement_id') and payment.agreement_id:
            logger.info(f"Processing agreement payment for agreement_id: {payment.agreement_id}")
            agreement = db.query(GeneralAgreement).filter(GeneralAgreement.id == payment.agreement_id).first()
            if agreement:
                logger.info(f"Loaded agreement status: {agreement.status}, Asset Type: {agreement.asset_type}")
                previous_status = agreement.status
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

                # Persist core payment/agreement state BEFORE any notification.
                # Notifications are best-effort: if one fails (e.g. a type
                # missing from the DB enum), _safe_notify rolls back only the
                # notification while the payment itself stays completed.
                try:
                    db.commit()
                except Exception:
                    db.rollback()
                    raise

                # Resolve asset title for richer email content (non-critical).
                asset_title = None
                try:
                    from core.asset_service import asset_service
                    asset_obj = asset_service._get_asset_details(db, agreement.asset_type, agreement.asset_id)
                    if asset_obj and asset_obj.title:
                        asset_title = asset_obj.title
                except Exception:
                    pass  # non-critical
                asset_title = asset_title or f"{agreement.asset_type.title()} asset"

                agreement_ref = _ref(agreement.id)
                total_paid = Decimal(str(agreement.total_price or 0)) - Decimal(str(agreement.remaining_balance or 0))
                next_due_str = agreement.next_due_date.strftime("%B %d, %Y") if agreement.next_due_date else None
                monthly = (
                    float(agreement.monthly_installment)
                    if agreement.monthly_installment is not None else None
                )

                # The deposit payment that flips the agreement out of
                # "pending_deposit" is the activation event: send a dedicated
                # "Agreement Activated" email instead of the generic payment
                # confirmation (which is kept for later installments).
                is_activation = (
                    previous_status == "pending_deposit"
                    and agreement.status in ("active", "completed")
                )

                if is_activation:
                    _safe_notify(db, {
                        "user_id": str(payment.buyer_id),
                        "type": "agreement_activated",
                        "title": "Agreement Activated",
                        "message": (
                            f"Your deposit for {asset_title} has been confirmed and your "
                            f"agreement is now active."
                        ),
                        "priority": "high",
                        "channels": ["in_app", "email"],
                        "data": {
                            "asset_title": asset_title,
                            "total_price": float(agreement.total_price or 0),
                            "amount_paid": float(total_paid),
                            "remaining_balance": float(agreement.remaining_balance or 0),
                            "monthly_installment": monthly,
                            "next_due_date": next_due_str,
                            "reference": agreement_ref,
                        },
                    })
                    _notify_admins_of_payment(
                        db, payment,
                        f"{agreement.asset_type} agreement deposit ({asset_title})",
                        {"payment_id": str(payment.id),
                         "agreement_id": str(agreement.id),
                         "amount": float(payment.amount or 0)},
                    )
                else:
                    _safe_notify(db, {
                        "user_id": str(payment.buyer_id),
                        "type": "payment_successful",
                        "title": "Agreement Payment Confirmed",
                        "message": (
                            f"Your payment of ₦{payment.amount:,.2f} for your {agreement.asset_type} "
                            f"agreement has been confirmed. Next payment due on "
                            f"{next_due_str or 'N/A'}."
                        ),
                        "priority": "high",
                        "channels": ["in_app", "email"],
                        "data": {
                            "context": "agreement",
                            "payment_id": str(payment.id),
                            "reference": agreement_ref,
                            "amount": float(payment.amount or 0),
                            "amount_paid": float(total_paid),
                            "remaining_balance": float(agreement.remaining_balance or 0),
                            "total_amount": float(agreement.total_price or 0),
                            "next_due_date": next_due_str,
                        },
                    })
                    _notify_admins_of_payment(
                        db, payment,
                        f"{agreement.asset_type} agreement ({asset_title})",
                        {"payment_id": str(payment.id),
                         "agreement_id": str(agreement.id),
                         "amount": float(payment.amount or 0)},
                    )

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
                    _safe_notify(db, {
                        "user_id": str(payment.buyer_id),
                        "type": "agreement_completed",
                        "title": f"🎉 Congratulations! You now own this {asset_noun}!",
                        "message": f"Your {agreement.asset_type} agreement has been fully paid. You are now the full owner of this asset. Thank you for choosing us!",
                        "priority": "urgent",
                        "channels": ["in_app", "email"],
                        "data": {
                            "asset_title": asset_title,
                            "reference": agreement_ref,
                            "total_paid": float(total_paid),
                            "completed_date": datetime.utcnow().strftime("%B %d, %Y"),
                            "asset_noun": asset_noun,
                        },
                    })

        db.commit()
        
    def handle_mandate_webhook(self, db: Session, event: str, tx_ref: str, flw_data: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """Handle tokenized-installment webhooks that carry no local Payment row yet.

        With Flutterwave tokenization there is no separate Direct-Debit mandate
        lifecycle: activation happens when the first card charge returns a token
        (see ``_maybe_capture_card_mandate``). This hook only handles late
        failure notifications for tokenized charges — e.g. a 3DS-pending
        installment that ultimately failed. Returns None when the ``tx_ref``
        belongs to a regular Payment (normal Payment-based handling applies).
        """
        payment = db.query(Payment).filter(
            (Payment.reference == tx_ref) | (Payment.transaction_id == tx_ref)
        ).first()
        if payment:
            return None

        status_raw = str((flw_data or {}).get("status") or "").lower()
        if status_raw in ("failed", "cancelled", "expired"):
            mandate = db.query(PaymentMandate).filter(PaymentMandate.reference == tx_ref).first()
            if mandate:
                mandate.failed_attempts = (mandate.failed_attempts or 0) + 1
                db.commit()
                logger.info(f"Mandate {mandate.id} installment failed via webhook ({tx_ref})")
                return {"status": "success"}
        logger.info(f"Ignoring non-actionable mandate webhook for reference {tx_ref} (event={event})")
        return {"status": "ignored", "reason": "mandate_not_actionable"}

    def charge_mandate_installment(self, db: Session, agreement: GeneralAgreement, mandate: PaymentMandate) -> Payment:
        """Attempt one recurring installment charge against an active card-token
        mandate (called by the daily `charge_due_mandates` celery task). Creates a
        Payment row; if Flutterwave responds synchronously with success, completes it
        immediately via the normal completion path. A pending/async response is left
        for the `charge.completed` webhook to resolve later."""
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
            payment_method=self.PROVIDER,
        )
        db.add(payment)
        db.flush()
        payment.receipt_number = derive_receipt_number(payment)
        db.commit()

        try:
            flw_res = self.flw.create_tokenized_charge(
                token=mandate.authorization_code,
                email=mandate.email,
                amount=float(amount),
                tx_ref=reference,
                narration=f"Installment for agreement {agreement.id}",
            )
        except Exception as e:
            logger.error(f"Mandate charge failed to reach Flutterwave for agreement {agreement.id}: {e}")
            payment.status = "failed"
            mandate.failed_attempts = (mandate.failed_attempts or 0) + 1
            db.commit()
            return payment

        flw_data = flw_res.get("data") or {}
        self._store_provider_ids(payment, flw_data, channel="card_token")
        db.commit()
        flw_status = str(flw_data.get("status") or "").lower()
        if flw_res.get("status") == "success" and flw_status == "successful":
            self._handle_completion(db, payment)
            mandate.failed_attempts = 0
            db.commit()
        elif flw_status in ["failed", "cancelled", "expired"]:
            payment.status = "failed"
            mandate.failed_attempts = (mandate.failed_attempts or 0) + 1
            db.commit()
        # else: pending/processing - the charge.completed webhook resolves it later.

        return payment

    def refund_payment(
        self,
        db: Session,
        payment_id: str,
        admin_id: str,
        reason: str = "Requested by admin/buyer"
    ) -> Payment:
        """Process a refund via Flutterwave and update local records.

        Only payments originally processed through Flutterwave (with a stored
        ``flw_id``) can be refunded via API. Legacy Paystack rows must be
        refunded manually through the Paystack dashboard.
        """
        payment = db.query(Payment).filter(Payment.id == payment_id).first()
        
        if not payment:
            raise HTTPException(status_code=404, detail="Payment not found")
            
        if payment.status != "completed":
            raise HTTPException(status_code=400, detail=f"Cannot refund a payment with status '{payment.status}'")
            
        if payment.payment_method != self.PROVIDER:
            raise HTTPException(status_code=400, detail="Only Flutterwave payments can be refunded via API. Legacy payments must be refunded manually.")

        flw_id = (payment.transaction_metadata or {}).get("flw_id")
        if not flw_id:
            raise HTTPException(status_code=400, detail="No Flutterwave transaction id stored for this payment; refund it manually.")

        # Call Flutterwave refund
        try:
            refund_res = self.flw.initiate_refund(
                flw_transaction_id=int(flw_id),
                amount=float(payment.amount),
            )

            if refund_res.get("status"):
                payment.status = "refunded"
                payment.transaction_metadata = {**(payment.transaction_metadata or {}), "refund_reason": reason, "refunded_by": str(admin_id), "refund_data": refund_res.get("data")}
                # Persist refund state before the best-effort notification so a
                # notification failure can never lose a completed Flutterwave refund.
                try:
                    db.commit()
                except Exception:
                    db.rollback()
                    raise

                # Notify Buyer (best-effort)
                _safe_notify(db, {
                    "user_id": str(payment.buyer_id),
                    "type": "payment_refunded",
                    "title": "Payment Refunded",
                    "message": f"Your payment of ₦{payment.amount:,.2f} has been refunded. Reason: {reason}",
                    "channels": ["in_app", "email"],
                    "data": {
                        "amount": float(payment.amount or 0),
                        "reason": reason,
                        "reference": payment.reference,
                    },
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
