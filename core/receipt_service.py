"""Payment receipts.

A receipt is an acknowledgement that money was received, so it is keyed to a
`Payment` (the atomic money-movement record) rather than to an `Order`. A single
order can be settled by several payments (partial payments, installments), and
payments also exist for asset agreements that have no order at all. Tying the
receipt to the payment keeps one receipt per actual transaction and lets the
same document serve order, deposit, installment and full-pay payments.
"""

from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
from typing import Any, Dict, Optional
from uuid import UUID

from jinja2 import Environment, FileSystemLoader, select_autoescape
from sqlalchemy.orm import Session

from core.model import Order, OrderItem, Payment, Product, Profile, StoreProfile, User


CURRENCY = "NGN"

# The receipt markup lives in a single editable template so every receipt
# (order, deposit, installment, full payment) shares one design.
_TEMPLATE_DIR = Path(__file__).resolve().parent / "templates"
_receipt_env = Environment(
    loader=FileSystemLoader(str(_TEMPLATE_DIR)),
    autoescape=select_autoescape(["html", "xml"]),
    trim_blocks=True,
    lstrip_blocks=True,
)

PURPOSE_LABELS = {
    "order": "Order payment",
    "asset_deposit": "Asset deposit",
    "asset_installment": "Asset installment",
    "full_pay": "Full payment",
}


def _money(value: Optional[Decimal]) -> str:
    if value is None:
        return f"{CURRENCY} 0.00"
    return f"{CURRENCY} {Decimal(value):,.2f}"


def derive_receipt_number(payment: Payment) -> str:
    """Derive the receipt number for a payment.

    Used at creation time to populate `payments.receipt_number`, and as a
    fallback when rendering a receipt for a payment that has none stored
    (e.g. rows predating the column, or a creation path that missed it).
    """
    created = payment.created_at or datetime.now(timezone.utc)
    return f"RCPT-{created:%Y%m%d}-{str(payment.id).replace('-', '')[:8].upper()}"


def _asset_name(payment: Payment) -> Optional[str]:
    agreement = payment.agreement
    if not agreement:
        return None
    if agreement.asset_type == "automotive" and agreement.car:
        car = agreement.car
        return f"{car.year} {car.brand} {car.model}".strip()
    if agreement.asset_type == "property" and agreement.property:
        return agreement.property.title
    return None


def _order_lines(db: Session, order: Order) -> Dict[str, Any]:
    items = (
        db.query(OrderItem, Product.name)
        .outerjoin(Product, OrderItem.product_id == Product.id)
        .filter(OrderItem.order_id == order.id)
        .all()
    )

    lines = []
    subtotal = Decimal("0.00")
    for item, product_name in items:
        line_total = (item.price or Decimal("0.00")) * (item.quantity or 0)
        subtotal += line_total
        lines.append(
            {
                "name": product_name or "Item",
                "quantity": item.quantity,
                "unit_price": item.price,
                "line_total": line_total,
                "status": item.status,
            }
        )

    delivery_fee = order.delivery_fee or Decimal("0.00")
    return {
        "id": order.id,
        "status": order.status,
        "created_at": order.created_at,
        "items": lines,
        "subtotal": subtotal,
        "delivery_fee": delivery_fee,
        "total": subtotal + delivery_fee,
    }


def build_receipt(db: Session, payment: Payment) -> Dict[str, Any]:
    """Build a serialisable receipt for a payment (no access checks here)."""
    buyer_profile = (
        db.query(Profile).filter(Profile.id == payment.buyer_id).first()
        if payment.buyer_id
        else None
    )
    buyer_user = (
        db.query(User).filter(User.id == payment.buyer_id).first()
        if payment.buyer_id
        else None
    )
    seller = (
        db.query(StoreProfile).filter(StoreProfile.id == payment.seller_id).first()
        if payment.seller_id
        else db.query(StoreProfile).first()
    )

    order = payment.order
    if order is None and payment.order_id:
        order = db.query(Order).filter(Order.id == payment.order_id).first()

    agreement = payment.agreement
    agreement_block = None
    if agreement:
        agreement_block = {
            "id": agreement.id,
            "asset_type": agreement.asset_type,
            "asset_name": _asset_name(payment),
            "payment_plan": agreement.payment_plan,
            "plan_type": agreement.plan_type,
            "total_price": agreement.total_price,
            "remaining_balance": agreement.remaining_balance,
        }

    return {
        "receipt_number": payment.receipt_number or derive_receipt_number(payment),
        "issued_at": datetime.now(timezone.utc),
        "currency": CURRENCY,
        "amount": payment.amount,
        "amount_display": _money(payment.amount),
        "status": payment.status,
        "reference": payment.reference,
        "transaction_id": payment.transaction_id,
        "payment_method": payment.payment_method,
        "payment_category": payment.payment_category,
        "payment_type": payment.payment_type,
        "purpose": PURPOSE_LABELS.get(payment.payment_category, "Payment"),
        "paid_at": payment.created_at,
        "payer": {
            "name": (buyer_profile.name if buyer_profile else None),
            "email": (buyer_user.email if buyer_user else None),
        },
        "payee": {
            "name": seller.business_name if seller else "LEL Store",
            "email": seller.contact_email if seller else None,
            "phone": seller.contact_phone if seller else None,
        },
        "order": _order_lines(db, order) if order else None,
        "agreement": agreement_block,
    }


def get_receipt(db: Session, user: Dict[str, Any], payment_id: UUID) -> Optional[Dict[str, Any]]:
    """Return a receipt for a payment the caller is allowed to see.

    Customers may only see their own payments; the store side (admin) may see
    payments belonging to the store.
    """
    payment = db.query(Payment).filter(Payment.id == payment_id).first()
    if not payment:
        return None

    if user["role"] == "admin":
        store = db.query(StoreProfile).first()
        if payment.seller_id and store and payment.seller_id != store.id:
            return None
    elif payment.buyer_id != UUID(str(user["id"])):
        return None

    return build_receipt(db, payment)


def _related_label(order: Optional[Dict[str, Any]], agreement: Optional[Dict[str, Any]]) -> str:
    if order:
        return f"Order #{str(order['id']).split('-')[0].upper()}"
    if agreement:
        return f"Agreement #{str(agreement['id']).split('-')[0].upper()}"
    return ""


def render_receipt_html(receipt: Dict[str, Any]) -> str:
    """Render a self-contained, printable HTML receipt (use the browser's
    print-to-PDF to save a copy).

    The markup itself is `core/templates/receipt.html`; edit that file to change
    the receipt for every payment type at once.
    """
    order = receipt.get("order")
    agreement = receipt.get("agreement")

    template = _receipt_env.get_template("receipt.html")
    return template.render(
        receipt=receipt,
        payer=receipt["payer"],
        payee=receipt["payee"],
        order=order,
        agreement=agreement,
        related=_related_label(order, agreement),
        money=_money,
    )
