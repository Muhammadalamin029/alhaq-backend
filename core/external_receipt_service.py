"""Receipts for admin-recorded external payments.

Reuses the site's normal receipt renderer (`render_receipt_html` over
`core/templates/receipt.html`) WITHOUT modifying it: we shape external data
into the exact dict the renderer already expects (receipt/payer/payee/order).
The ad-hoc items ride in the `order` block with delivery_fee 0.
"""

from datetime import datetime, timezone
from decimal import Decimal
from typing import Any, Dict
from uuid import UUID

from sqlalchemy.orm import Session

from core.model import ExternalPayment, StoreProfile
from core.receipt_service import CURRENCY, render_receipt_html


CHANNEL_LABELS = {
    "cash": "Cash",
    "bank_transfer": "Bank Transfer",
    "pos": "POS",
}


def _money(value) -> str:
    if value is None:
        return f"{CURRENCY} 0.00"
    return f"{CURRENCY} {Decimal(value):,.2f}"


def _as_aware(value: Any) -> Any:
    # receipt.html calls strftime on these; ensure tz-aware datetimes.
    if isinstance(value, datetime) and value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value


def build_external_receipt_dict(
    db: Session, payment: ExternalPayment
) -> Dict[str, Any]:
    """Build a renderer-ready receipt dict for an external payment."""
    items = []
    subtotal = Decimal("0.00")
    for line in (payment.items or []):
        line_total = (line.unit_price or Decimal("0.00")) * (line.quantity or 0)
        subtotal += line_total
        items.append(
            {
                "name": line.description
                and f"{line.name} — {line.description}"
                or line.name,
                "quantity": line.quantity,
                "unit_price": line.unit_price,
                "line_total": line_total,
                "status": "paid",
            }
        )

    seller = db.query(StoreProfile).first()
    now = datetime.now(timezone.utc)

    return {
        "receipt_number": payment.receipt_number,
        "issued_at": now,
        "currency": CURRENCY,
        "amount": payment.amount,
        "amount_display": _money(payment.amount),
        "status": "completed",
        "reference": payment.receipt_number,
        "transaction_id": None,
        "payment_method": CHANNEL_LABELS.get(payment.channel, payment.channel),
        "payment_category": "order",
        "payment_type": None,
        "purpose": "External sale",
        # The shared template derives a "Related Order #…" label from the
        # order block; suppress it — there is no real order here.
        "show_related": False,
        "paid_at": _as_aware(payment.paid_at) or now,
        "payer": {
            "name": payment.payer_name,
            "email": payment.payer_email,
            "phone": payment.payer_phone,
        },
        "payee": {
            "name": seller.business_name if seller else "LEL Store",
            "email": seller.contact_email if seller else None,
            "phone": seller.contact_phone if seller else None,
        },
        "order": {
            "id": payment.id,
            "status": "paid",
            "created_at": _as_aware(payment.created_at),
            "items": items,
            "subtotal": subtotal,
            "delivery_fee": Decimal("0.00"),
            "total": subtotal,
        },
        "agreement": None,
    }


def render_external_receipt_html(db: Session, payment_id: UUID) -> str | None:
    """Render the normal receipt HTML for an external payment, or None."""
    payment = (
        db.query(ExternalPayment).filter(ExternalPayment.id == payment_id).first()
    )
    if not payment:
        return None
    return render_receipt_html(build_external_receipt_dict(db, payment))
