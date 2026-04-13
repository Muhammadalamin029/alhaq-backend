from fastapi import APIRouter, Depends, HTTPException, status, Query
from sqlalchemy.orm import Session, joinedload
from sqlalchemy import func, desc, and_
from datetime import datetime, timedelta
from typing import Dict, Any, List, Optional
from decimal import Decimal

from db.session import get_db
from core.auth import role_required
from core.model import Order, OrderItem, Product, Wishlist, Profile, GeneralInspection, GeneralAgreement, Payment
from core.status_constants import (
    AGREEMENT_PENDING_STATUSES,
    AGREEMENT_STATUS_ACTIVE,
    INSPECTION_PENDING_STATUSES,
)

router = APIRouter()

@router.get("/customer/stats")
async def get_customer_dashboard_stats(
    user=Depends(role_required(["customer"])),
    db: Session = Depends(get_db),
    range: Optional[str] = Query(None, pattern="^(today|7d|30d)$"),
) -> Dict[str, Any]:
    """Get customer dashboard statistics"""
    try:
        from uuid import UUID
        user_id = UUID(user["id"])
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid user id")
    
    # Get total orders count
    total_orders = db.query(Order).filter(Order.buyer_id == user_id).count()
    
    # Total spent (gross): sum of all completed payments (orders + asset payments)
    total_spent_result = (
        db.query(func.sum(Payment.amount))
        .filter(
            Payment.buyer_id == user_id,
            Payment.status == "completed",
        )
        .scalar()
    )
    total_spent = float(total_spent_result) if total_spent_result else 0.0
    
    # Get wishlist items count
    wishlist_count = db.query(Wishlist).filter(Wishlist.user_id == user_id).count()
    
    # Get recent orders (last 5)
    recent_orders = (
        db.query(Order)
        .filter(Order.buyer_id == user_id)
        .order_by(Order.created_at.desc())
        .limit(5)
        .all()
    )
    
    # Get pending order (cart) info
    pending_order = db.query(Order).filter(
        and_(Order.buyer_id == user_id, Order.status == "pending")
    ).first()
    
    cart_items_count = 0
    cart_total = 0.0
    if pending_order:
        cart_items_count = db.query(func.sum(OrderItem.quantity)).filter(
            OrderItem.order_id == pending_order.id
        ).scalar() or 0
        cart_total = float(pending_order.total_amount)
    
    # Calculate this month's stats for comparison
    current_month_start = datetime.now().replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    last_month_start = (current_month_start - timedelta(days=1)).replace(day=1)
    
    # This month's orders
    current_month_orders = db.query(Order).filter(
        and_(
            Order.buyer_id == user_id,
            Order.created_at >= current_month_start
        )
    ).count()
    
    # Last month's orders
    last_month_orders = db.query(Order).filter(
        and_(
            Order.buyer_id == user_id,
            Order.created_at >= last_month_start,
            Order.created_at < current_month_start
        )
    ).count()
    
    # Calculate order change
    order_change = current_month_orders - last_month_orders
    
    # This month's spending (gross): completed payments this month
    current_month_spent = (
        db.query(func.sum(Payment.amount))
        .filter(
            Payment.buyer_id == user_id,
            Payment.created_at >= current_month_start,
            Payment.status == "completed",
        )
        .scalar() or 0
    )
    
    # Last month's spending (gross): completed payments last month
    last_month_spent = (
        db.query(func.sum(Payment.amount))
        .filter(
            Payment.buyer_id == user_id,
            Payment.created_at >= last_month_start,
            Payment.created_at < current_month_start,
            Payment.status == "completed",
        )
        .scalar() or 0
    )
    
    # Calculate spending change
    spending_change = float(current_month_spent) - float(last_month_spent)

    # ---------------- ASSET STATS (Inspections & Agreements) ----------------
    total_inspections = db.query(GeneralInspection).filter(GeneralInspection.user_id == user_id).count()
    pending_inspections = db.query(GeneralInspection).filter(
        and_(
            GeneralInspection.user_id == user_id,
            GeneralInspection.status.in_(INSPECTION_PENDING_STATUSES)
        )
    ).count()

    total_agreements = db.query(GeneralAgreement).filter(GeneralAgreement.user_id == user_id).count()
    pending_agreements = db.query(GeneralAgreement).filter(
        and_(
            GeneralAgreement.user_id == user_id,
            GeneralAgreement.status.in_(AGREEMENT_PENDING_STATUSES)
        )
    ).count()
    active_agreements = db.query(GeneralAgreement).filter(
        and_(GeneralAgreement.user_id == user_id, GeneralAgreement.status == AGREEMENT_STATUS_ACTIVE)
    ).count()

    # ---------------- Range analytics (optional) ----------------
    now = datetime.utcnow()
    range_end = now
    range_start = None
    if range == "today":
        range_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    elif range == "7d":
        range_start = now - timedelta(days=7)
    elif range == "30d":
        range_start = now - timedelta(days=30)

    previous_range_start = None
    previous_range_end = None
    if range == "today":
        previous_range_end = range_start
        previous_range_start = (range_start - timedelta(days=1)) if range_start else None
    elif range == "7d":
        previous_range_end = range_start
        previous_range_start = (range_start - timedelta(days=7)) if range_start else None
    elif range == "30d":
        previous_range_end = range_start
        previous_range_start = (range_start - timedelta(days=30)) if range_start else None

    range_spent = 0.0
    range_orders = 0
    previous_spent = 0.0
    previous_orders = 0
    spending_series: List[Dict[str, Any]] = []
    orders_series: List[Dict[str, Any]] = []
    inspections_series: List[Dict[str, Any]] = []
    agreements_series: List[Dict[str, Any]] = []

    if range_start:
        range_spent_result = (
            db.query(func.sum(Payment.amount))
            .filter(
                Payment.buyer_id == user_id,
                Payment.status == "completed",
                Payment.created_at >= range_start,
            )
            .scalar()
        )
        range_spent = float(range_spent_result) if range_spent_result else 0.0

        range_orders = (
            db.query(Order)
            .filter(and_(Order.buyer_id == user_id, Order.created_at >= range_start))
            .count()
        )

        if previous_range_start is not None and previous_range_end is not None:
            prev_spent_result = (
                db.query(func.sum(Payment.amount))
                .filter(
                    Payment.buyer_id == user_id,
                    Payment.status == "completed",
                    Payment.created_at >= previous_range_start,
                    Payment.created_at < previous_range_end,
                )
                .scalar()
            )
            previous_spent = float(prev_spent_result) if prev_spent_result else 0.0

            previous_orders = (
                db.query(Order)
                .filter(
                    and_(
                        Order.buyer_id == user_id,
                        Order.created_at >= previous_range_start,
                        Order.created_at < previous_range_end,
                    )
                )
                .count()
            )

        spending_rows = (
            db.query(func.date(Payment.created_at).label("date"), func.sum(Payment.amount).label("spent"))
            .filter(
                Payment.buyer_id == user_id,
                Payment.status == "completed",
                Payment.created_at >= range_start,
            )
            .group_by(func.date(Payment.created_at))
            .order_by(func.date(Payment.created_at))
            .all()
        )
        spending_series = [{"date": str(r.date), "spent": float(r.spent or 0)} for r in spending_rows]

        order_rows = (
            db.query(func.date(Order.created_at).label("date"), func.count(Order.id).label("count"))
            .filter(and_(Order.buyer_id == user_id, Order.created_at >= range_start))
            .group_by(func.date(Order.created_at))
            .order_by(func.date(Order.created_at))
            .all()
        )
        orders_series = [{"date": str(r.date), "count": int(r.count)} for r in order_rows]

        inspection_rows = (
            db.query(func.date(GeneralInspection.created_at).label("date"), func.count(GeneralInspection.id).label("count"))
            .filter(and_(GeneralInspection.user_id == user_id, GeneralInspection.created_at >= range_start))
            .group_by(func.date(GeneralInspection.created_at))
            .order_by(func.date(GeneralInspection.created_at))
            .all()
        )
        inspections_series = [{"date": str(r.date), "count": int(r.count)} for r in inspection_rows]

        agreement_rows = (
            db.query(func.date(GeneralAgreement.created_at).label("date"), func.count(GeneralAgreement.id).label("count"))
            .filter(and_(GeneralAgreement.user_id == user_id, GeneralAgreement.created_at >= range_start))
            .group_by(func.date(GeneralAgreement.created_at))
            .order_by(func.date(GeneralAgreement.created_at))
            .all()
        )
        agreements_series = [{"date": str(r.date), "count": int(r.count)} for r in agreement_rows]

    overdue_agreements = (
        db.query(GeneralAgreement)
        .filter(
            GeneralAgreement.user_id == user_id,
            GeneralAgreement.status == AGREEMENT_STATUS_ACTIVE,
            GeneralAgreement.next_due_date.isnot(None),
            GeneralAgreement.next_due_date < now,
        )
        .count()
    )

    alerts = {
        "cart_items": int(cart_items_count or 0),
        "cart_total": float(cart_total or 0.0),
        "wishlist_items": int(wishlist_count or 0),
        "pending_inspections": int(pending_inspections or 0),
        "pending_agreements": int(pending_agreements or 0),
        "overdue_agreements": int(overdue_agreements or 0),
    }
    
    return {
        "total_orders": total_orders,
        "total_spent": total_spent,
        "wishlist_items": wishlist_count,
        "cart_items": cart_items_count,
        "cart_total": cart_total,
        "asset_stats": {
            "total_inspections": total_inspections,
            "pending_inspections": pending_inspections,
            "total_agreements": total_agreements,
            "pending_agreements": pending_agreements,
            "active_agreements": active_agreements,
        },
        "recent_orders": [
            {
                "id": order.id,
                "total_amount": float(order.total_amount),
                "status": order.status,
                "created_at": order.created_at.isoformat(),
                "items_count": len(order.order_items) if order.order_items else 0
            }
            for order in recent_orders
        ],
        "monthly_comparison": {
            "orders_change": order_change,
            "spending_change": spending_change,
            "current_month_orders": current_month_orders,
            "current_month_spent": float(current_month_spent)
        },
        "range": range,
        "range_start": range_start.isoformat() if range_start else None,
        "range_end": range_end.isoformat() if range_end else None,
        "range_spent": range_spent,
        "range_orders": range_orders,
        "period_comparison": {
            "spending_change": (range_spent - previous_spent) if range_start else 0.0,
            "orders_change": (range_orders - previous_orders) if range_start else 0,
            "previous_spent": previous_spent,
            "previous_orders": previous_orders,
            "current_spent": range_spent,
            "current_orders": range_orders,
        },
        "spending_series": spending_series,
        "orders_series": orders_series,
        "inspections_series": inspections_series,
        "agreements_series": agreements_series,
        "alerts": alerts,
    }
