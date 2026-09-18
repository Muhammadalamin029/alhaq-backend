"""Derived installment state for product Orders.

There is deliberately no installment table: the plan is reconstructed from the
existing ``payments`` ledger exactly like the parent entity does for assets. Every
read recomputes from completed ``payment_type='installment'`` rows so retries,
webhook replays, and refunds can never drift.
"""

from decimal import Decimal
from typing import Any, Dict, Optional

from fastapi import HTTPException
from sqlalchemy.orm import Session

from core.model import Order, Payment
from core.system_settings_service import system_settings_service

INSTALLMENT = "installment"
_PAYABLE_STATUSES = ("pending", "processing")


def _to_decimal(value: Any) -> Decimal:
    return Decimal(str(value if value is not None else 0))


def _payments(db: Session, order: Order):
    payments = getattr(order, "payments", None)
    if payments is None:
        return db.query(Payment).filter(Payment.order_id == order.id).all()
    return payments


def _is_completed(payment: Payment) -> bool:
    return payment.status == "completed"


def _completed_installment_total(payments) -> Decimal:
    return sum(
        (
            _to_decimal(payment.amount)
            for payment in payments
            if _is_completed(payment) and (payment.payment_type or "") == INSTALLMENT
        ),
        Decimal("0.00"),
    )


def _has_completed_one_shot(payments) -> bool:
    """True when a completed payment was made outside an installment plan."""
    return any(
        _is_completed(payment) and (payment.payment_type or "") != INSTALLMENT
        for payment in payments
    )


def summarize(db: Session, order: Order) -> Dict[str, Any]:
    """Derive the installment summary for an order from its payments ledger."""
    payments = _payments(db, order)
    is_installment = any(
        (payment.payment_type or "") == INSTALLMENT for payment in payments
    )
    total = _to_decimal(order.total_amount)
    amount_paid = _completed_installment_total(payments)
    remaining = max(Decimal("0.00"), total - amount_paid)
    fully_paid = is_installment and remaining <= 0
    active = bool(is_installment and remaining > 0 and order.status in _PAYABLE_STATUSES)

    return {
        "is_installment": bool(is_installment),
        "amount_paid": float(amount_paid),
        "remaining_balance": float(remaining),
        "fully_paid": bool(fully_paid),
        "active": active,
    }


def build_eligibility(db: Session, order: Order) -> Dict[str, Any]:
    """Describe whether an order can (still) be paid via an installment plan."""
    settings = system_settings_service.get_payment_setting_values(db)
    min_percent = _to_decimal(settings.get("installment_min_percent"))
    price_floor = _to_decimal(settings.get("installment_price_floor"))

    payments = _payments(db, order)
    total = _to_decimal(order.total_amount)
    amount_paid = _completed_installment_total(payments)
    remaining = max(Decimal("0.00"), total - amount_paid)
    is_installment = any(
        (payment.payment_type or "") == INSTALLMENT for payment in payments
    )
    min_initial = (min_percent / Decimal("100")) * total

    eligible = True
    reason: Optional[str] = None

    if order.status not in _PAYABLE_STATUSES:
        eligible, reason = False, "This order can no longer receive payments"
    elif total < price_floor:
        eligible, reason = (
            False,
            f"Installment plans are only available for orders of ₦{price_floor:,.2f} or more",
        )
    elif remaining <= 0:
        eligible, reason = False, "This order has no outstanding balance"
    elif _has_completed_one_shot(payments):
        eligible, reason = False, "This order has already been paid in full"

    return {
        "eligible": eligible,
        "reason": reason,
        "total_amount": float(total),
        "amount_paid": float(amount_paid),
        "remaining_balance": float(remaining),
        "min_percent": float(min_percent),
        "price_floor": float(price_floor),
        "min_initial_amount": float(min_initial),
        "is_installment": bool(is_installment),
    }


def validate_installment_payment(
    db: Session, user_id: str, order: Order, amount_naira: Any
) -> None:
    """Raise HTTPException(400/403/404) when an installment payment is not allowed."""
    if order is None:
        raise HTTPException(status_code=404, detail="Order not found")

    if str(order.buyer_id) != str(user_id):
        raise HTTPException(
            status_code=403, detail="You can only pay for your own orders"
        )

    if order.status not in _PAYABLE_STATUSES:
        raise HTTPException(
            status_code=400,
            detail="This order can no longer receive installment payments",
        )

    payments = _payments(db, order)

    if _has_completed_one_shot(payments):
        raise HTTPException(
            status_code=400, detail="This order has already been paid in full"
        )

    total = _to_decimal(order.total_amount)
    amount_paid = _completed_installment_total(payments)
    remaining = max(Decimal("0.00"), total - amount_paid)

    if remaining <= 0:
        raise HTTPException(
            status_code=400, detail="This order has no outstanding balance"
        )

    settings = system_settings_service.get_payment_setting_values(db)
    price_floor = _to_decimal(settings.get("installment_price_floor"))
    if total < price_floor:
        raise HTTPException(
            status_code=400,
            detail=f"Installment plans are only available for orders of ₦{price_floor:,.2f} or more",
        )

    amount = _to_decimal(amount_naira)
    if amount <= 0:
        raise HTTPException(
            status_code=400, detail="Payment amount must be greater than zero"
        )

    if amount > remaining:
        raise HTTPException(
            status_code=400,
            detail=f"Payment amount cannot exceed the outstanding balance of ₦{remaining:,.2f}",
        )

    if amount_paid == 0:
        min_percent = _to_decimal(settings.get("installment_min_percent"))
        min_initial = (min_percent / Decimal("100")) * total
        if amount < min_initial:
            raise HTTPException(
                status_code=400,
                detail=(
                    f"An initial payment of at least {min_percent:g}% "
                    f"(₦{min_initial:,.2f}) is required to start an installment plan"
                ),
            )


class OrderInstallmentService:
    summarize = staticmethod(summarize)
    build_eligibility = staticmethod(build_eligibility)
    validate_installment_payment = staticmethod(validate_installment_payment)


order_installment_service = OrderInstallmentService()
