from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session, joinedload
from sqlalchemy import func, desc, and_
from datetime import datetime, timedelta
from typing import Dict, Any, List
from decimal import Decimal

from db.session import get_db
from core.auth import role_required
from core.model import Order, OrderItem, Product, Wishlist, Profile

router = APIRouter()

@router.get("/customer/stats")
async def get_customer_dashboard_stats(
    user=Depends(role_required(["customer"])),
    db: Session = Depends(get_db),
) -> Dict[str, Any]:
    """Get customer dashboard statistics"""
    user_id = user["id"]
    
    # Get total orders count
    total_orders = db.query(Order).filter(Order.buyer_id == user_id).count()
    
    # Get total spent (sum of all non-pending/cancelled orders)
    total_spent_result = db.query(func.sum(Order.total_amount)).filter(
        and_(
            Order.buyer_id == user_id,
            Order.status.in_(["processing", "shipped", "delivered"])
        )
    ).scalar()
    total_spent = float(total_spent_result) if total_spent_result else 0.0
    
    # Get wishlist items count
    wishlist_count = db.query(Wishlist).filter(Wishlist.user_id == user_id).count()
    
    # Get recent orders (last 5)
    recent_orders = db.query(Order).filter(
        Order.buyer_id == user_id
    ).order_by(Order.created_at.desc()).limit(5).all()
    
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
    
    # This month's spending
    current_month_spent = db.query(func.sum(Order.total_amount)).filter(
        and_(
            Order.buyer_id == user_id,
            Order.created_at >= current_month_start,
            Order.status.in_(["processing", "shipped", "delivered"])
        )
    ).scalar() or 0
    
    # Last month's spending
    last_month_spent = db.query(func.sum(Order.total_amount)).filter(
        and_(
            Order.buyer_id == user_id,
            Order.created_at >= last_month_start,
            Order.created_at < current_month_start,
            Order.status.in_(["processing", "shipped", "delivered"])
        )
    ).scalar() or 0
    
    # Calculate spending change
    spending_change = float(current_month_spent) - float(last_month_spent)
    
    return {
        "total_orders": total_orders,
        "total_spent": total_spent,
        "wishlist_items": wishlist_count,
        "cart_items": cart_items_count,
        "cart_total": cart_total,
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
        }
    }
