"""Admin-recorded external (offline) payments.

Separate ledger from `payments` — no FK either way, no shared code paths.
The receipt PDF is generated on the FE, uploaded to Cloudinary, and only the
URL is stored here (V1: public unguessable URL).
"""

import secrets
from datetime import datetime, timezone
from decimal import Decimal
from typing import Optional
from uuid import UUID

from sqlalchemy.orm import Session

from core.model import ExternalPayment, ExternalPaymentItem, Profile, User
from schemas.external_payment import ExternalPaymentCreate


def _mint_receipt_number() -> str:
    day = datetime.now(timezone.utc).strftime("%Y%m%d")
    rand = secrets.token_hex(4).upper()
    return f"EXT-RCPT-{day}-{rand}"


def _resolve_buyer_id(db: Session, email: str) -> Optional[UUID]:
    user = db.query(User).filter(User.email.ilike(email.strip())).first()
    if not user:
        return None
    profile = db.query(Profile).filter(Profile.id == user.id).first()
    return profile.id if profile else None


def create_external_payment(
    db: Session,
    payload: ExternalPaymentCreate,
    recorded_by: UUID,
) -> ExternalPayment:
    total = sum(
        Decimal(str(i.unit_price)) * int(i.quantity) for i in payload.items
    )
    if total <= 0:
        raise ValueError("Total must be greater than zero")

    receipt_number = _mint_receipt_number()
    # Extremely unlikely collision; retry once on unique conflict at commit.
    for _ in range(3):
        exists = (
            db.query(ExternalPayment)
            .filter(ExternalPayment.receipt_number == receipt_number)
            .first()
        )
        if not exists:
            break
        receipt_number = _mint_receipt_number()

    payment = ExternalPayment(
        receipt_number=receipt_number,
        payer_name=payload.payer_name.strip(),
        payer_email=payload.payer_email.strip().lower(),
        payer_phone=(payload.payer_phone or None),
        buyer_id=_resolve_buyer_id(db, payload.payer_email),
        amount=total,
        channel=payload.channel,
        status="completed",
        notes=payload.notes,
        paid_at=payload.paid_at or datetime.now(timezone.utc),
        recorded_by=recorded_by,
    )
    db.add(payment)
    db.flush()  # id for items

    for item in payload.items:
        db.add(ExternalPaymentItem(
            external_payment_id=payment.id,
            name=item.name.strip(),
            description=(item.description.strip()
                         if item.description else None),
            quantity=int(item.quantity),
            unit_price=Decimal(str(item.unit_price)),
        ))
    db.commit()
    db.refresh(payment)
    return payment


def set_external_payment_pdf(
    db: Session, payment_id: UUID, pdf_url: str
) -> ExternalPayment:
    payment = (
        db.query(ExternalPayment).filter(ExternalPayment.id == payment_id).first()
    )
    if not payment:
        raise LookupError("External payment not found")
    payment.pdf_url = pdf_url.strip()
    db.commit()
    db.refresh(payment)
    return payment
