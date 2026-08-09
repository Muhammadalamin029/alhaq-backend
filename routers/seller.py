from decimal import Decimal
from fastapi import APIRouter, Depends, HTTPException, status, Query
from sqlalchemy.orm import Session, joinedload
from sqlalchemy import func, desc, case
from typing import Optional, List
from uuid import UUID
from datetime import datetime, timedelta

from db.session import get_db
from core.auth import role_required
from core.model import (
    Profile,
    SellerProfile,
    Product,
    Order,
    OrderItem,
    GeneralInspection,
    GeneralAgreement,
    Payment,
)
from schemas.products import ProductResponse
from schemas.order import (
    OrderResponse,
    OrderStatus,
    OrderStatusUpdate,
    OrderStatusResponse,
)
from schemas.seller import (
    SellerStatsResponse,
    SellerProductsResponse,
    SellerOrdersResponse,
    SellerAnalyticsResponse,
)
from core.commission_service import commission_service
from core.admin_service import admin_service
from core.logging_config import get_logger, log_error
from core.order import OrderService
from core.system_settings_service import system_settings_service
from core.status_constants import (
    AGREEMENT_PENDING_STATUSES,
    AGREEMENT_STATUS_ACTIVE,
    INSPECTION_PENDING_STATUSES,
)

# Get logger for seller routes
seller_logger = get_logger("routers.seller")

# Initialize order service
order_service = OrderService()
router = APIRouter()


def calculate_seller_item_status(order, seller_id: str) -> str:
    """Calculate seller's aggregate item status for an order, based solely on OrderItem statuses."""
    if not order.order_items:
        return "pending"

    seller_items = [
        item for item in order.order_items
        if item.product and str(item.product.seller_id) == str(seller_id)
    ]

    if not seller_items:
        return "cancelled" if order.status == "cancelled" else "pending"

    if order.status == "cancelled":
        return "cancelled"

    item_statuses = [item.status for item in seller_items]

    # Uniform statuses first
    for s in ("cancelled", "delivered", "shipped", "paid", "processing", "pending"):
        if all(st == s for st in item_statuses):
            return s

    # Mixed: return the most advanced status present
    for s in ("delivered", "shipped", "paid", "processing"):
        if s in item_statuses:
            return s

    return "pending"


# NOTE: Profile management (GET/PUT /profile) has been moved to /auth/me
# This eliminates code duplication and provides a unified API for all user types
# Use /auth/me for profile operations instead of /seller/profile


@router.get("/stats", response_model=SellerStatsResponse)
async def get_seller_stats(
    user=Depends(role_required(["seller", "admin"])),
    db: Session = Depends(get_db),
    range: Optional[str] = Query(None, pattern="^(today|7d|30d)$"),
):
    """Get seller statistics"""
    try:
        try:
            seller_id = UUID(user["id"])
        except Exception:
            raise HTTPException(status_code=400, detail="Invalid seller id")

        # Get basic stats from seller profile
        seller_profile = (
            db.query(SellerProfile).filter(SellerProfile.id == seller_id).first()
        )

        if not seller_profile:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="Seller profile not found"
            )

        # Product counts — query Product table directly so active/out-of-stock are consistent
        asset_counts = admin_service.get_asset_counts(db, seller_id=seller_id)

        total_products = asset_counts.get("products", 0)
        total_cars = asset_counts.get("cars", 0)
        total_properties = asset_counts.get("properties", 0)

        active_products = (
            db.query(Product)
            .filter(Product.seller_id == seller_id, Product.status == "active")
            .count()
        )

        out_of_stock_products = (
            db.query(Product)
            .filter(Product.seller_id == seller_id, Product.stock_quantity == 0)
            .count()
        )

        # Order counts — eager-load items+products to avoid N+1
        all_seller_orders = (
            db.query(Order)
            .join(OrderItem)
            .join(Product)
            .filter(Product.seller_id == seller_id)
            .options(
                joinedload(Order.order_items).joinedload(OrderItem.product)
            )
            .distinct()
            .all()
        )

        total_orders = len(all_seller_orders)
        pending_orders = processing_orders = paid_orders = 0
        shipped_orders = delivered_orders = cancelled_orders = 0

        for order in all_seller_orders:
            s = calculate_seller_item_status(order, str(seller_id))
            if s == "pending":         pending_orders += 1
            elif s == "processing":    processing_orders += 1
            elif s == "paid":          paid_orders += 1
            elif s == "shipped":       shipped_orders += 1
            elif s == "delivered":     delivered_orders += 1
            elif s == "cancelled":     cancelled_orders += 1

        now = datetime.utcnow()
        range_end = now
        range_start = None
        if range == "today":
            range_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
        elif range == "7d":
            range_start = now - timedelta(days=7)
        elif range == "30d":
            range_start = now - timedelta(days=30)

        # ---------------- Revenue ----------------
        # Payment.seller_id is NULL for regular order payments (only set for asset payments).
        # Use OrderItem × Product to compute order revenue; add asset payments separately.
        fee_rate = commission_service.get_platform_fee_rate(db)

        def _order_revenue_query(since=None):
            q = (
                db.query(func.sum(OrderItem.quantity * OrderItem.price))
                .join(Product, OrderItem.product_id == Product.id)
                .join(Order, OrderItem.order_id == Order.id)
                .filter(
                    Product.seller_id == seller_id,
                    Order.status.in_(["paid", "shipped", "delivered"]),
                )
            )
            if since:
                q = q.filter(Order.created_at >= since)
            return q.scalar() or Decimal("0")

        def _asset_revenue_query(since=None):
            q = db.query(func.sum(Payment.amount)).filter(
                Payment.seller_id == seller_id,
                Payment.status == "completed",
            )
            if since:
                q = q.filter(Payment.created_at >= since)
            return q.scalar() or Decimal("0")

        gross_revenue = Decimal(str(_order_revenue_query())) + Decimal(str(_asset_revenue_query()))
        if range_start:
            range_gross = Decimal(str(_order_revenue_query(range_start))) + Decimal(str(_asset_revenue_query(range_start)))
        else:
            range_gross = gross_revenue

        platform_fee_amount = gross_revenue * fee_rate
        net_revenue = gross_revenue - platform_fee_amount

        # ---------------- ASSET STATS ----------------
        total_inspections = (
            db.query(GeneralInspection)
            .filter(GeneralInspection.seller_id == seller_id)
            .count()
        )
        pending_inspections = (
            db.query(GeneralInspection)
            .filter(
                GeneralInspection.seller_id == seller_id,
                GeneralInspection.status.in_(INSPECTION_PENDING_STATUSES),
            )
            .count()
        )

        total_agreements = (
            db.query(GeneralAgreement)
            .filter(GeneralAgreement.seller_id == seller_id)
            .count()
        )
        pending_agreements = (
            db.query(GeneralAgreement)
            .filter(
                GeneralAgreement.seller_id == seller_id,
                GeneralAgreement.status.in_(AGREEMENT_PENDING_STATUSES),
            )
            .count()
        )
        active_agreements = (
            db.query(GeneralAgreement)
            .filter(
                GeneralAgreement.seller_id == seller_id,
                GeneralAgreement.status == AGREEMENT_STATUS_ACTIVE,
            )
            .count()
        )

        # ---------------- Chart series ----------------
        revenue_series: List[dict] = []
        orders_series: List[dict] = []
        agreements_series: List[dict] = []
        if range_start:
            revenue_rows = (
                db.query(
                    func.date(Order.created_at).label("date"),
                    func.sum(OrderItem.quantity * OrderItem.price).label("gross"),
                )
                .join(OrderItem, Order.id == OrderItem.order_id)
                .join(Product, OrderItem.product_id == Product.id)
                .filter(
                    Product.seller_id == seller_id,
                    Order.status.in_(["paid", "shipped", "delivered"]),
                    Order.created_at >= range_start,
                )
                .group_by(func.date(Order.created_at))
                .order_by(func.date(Order.created_at))
                .all()
            )
            revenue_series = [
                {
                    "date": str(r.date),
                    "gross": float(r.gross or 0),
                    "net": float(Decimal(str(r.gross or 0)) * (Decimal("1") - fee_rate)),
                    "platform_fee": float(Decimal(str(r.gross or 0)) * fee_rate),
                }
                for r in revenue_rows
            ]

            order_rows = (
                db.query(
                    func.date(Order.created_at).label("date"),
                    func.count(Order.id.distinct()).label("count"),
                )
                .join(OrderItem)
                .join(Product)
                .filter(Product.seller_id == seller_id, Order.created_at >= range_start)
                .group_by(func.date(Order.created_at))
                .order_by(func.date(Order.created_at))
                .all()
            )
            orders_series = [{"date": str(r.date), "count": int(r.count)} for r in order_rows]

            agreement_rows = (
                db.query(
                    func.date(GeneralAgreement.created_at).label("date"),
                    func.count(GeneralAgreement.id).label("count"),
                )
                .filter(
                    GeneralAgreement.seller_id == seller_id,
                    GeneralAgreement.created_at >= range_start,
                )
                .group_by(func.date(GeneralAgreement.created_at))
                .order_by(func.date(GeneralAgreement.created_at))
                .all()
            )
            agreements_series = [{"date": str(r.date), "count": int(r.count)} for r in agreement_rows]

        # ---------------- Alerts ----------------
        overdue_agreements = (
            db.query(GeneralAgreement)
            .filter(
                GeneralAgreement.seller_id == seller_id,
                GeneralAgreement.status == AGREEMENT_STATUS_ACTIVE,
                GeneralAgreement.next_due_date.isnot(None),
                GeneralAgreement.next_due_date < now,
            )
            .count()
        )
        alerts = {
            "overdue_agreements": overdue_agreements,
            "payout_account_configured": bool(
                seller_profile.payout_account_number and seller_profile.payout_bank_code
            ),
            "kyc_status": seller_profile.kyc_status,
        }

        # Recent orders — eager-load buyer for email, items already loaded above
        recent_orders_raw = (
            db.query(Order)
            .join(OrderItem)
            .join(Product)
            .filter(Product.seller_id == seller_id)
            .options(
                joinedload(Order.buyer).joinedload(Profile.user),
                joinedload(Order.order_items).joinedload(OrderItem.product),
            )
            .order_by(desc(Order.created_at))
            .distinct()
            .limit(5)
            .all()
        )

        recent_orders = []
        for order in recent_orders_raw:
            s_items = [
                item for item in order.order_items
                if item.product and str(item.product.seller_id) == str(seller_id)
            ]
            seller_amount = sum(item.quantity * item.price for item in s_items)
            recent_orders.append({
                "id": str(order.id),
                "status": order.status,
                "seller_item_status": calculate_seller_item_status(order, str(seller_id)),
                "total_amount": float(seller_amount),
                "items_count": len(s_items),
                "created_at": order.created_at.isoformat(),
                "buyer": {
                    "email": order.buyer.user.email if order.buyer and order.buyer.user else None
                },
            })

        recent_products = [
            {
                "id": str(p.id),
                "name": p.name,
                "price": float(p.price),
                "stock_quantity": p.stock_quantity,
                "status": p.status,
            }
            for p in (
                db.query(Product)
                .filter(Product.seller_id == seller_id)
                .order_by(desc(Product.created_at))
                .limit(3)
                .all()
            )
        ]

        return SellerStatsResponse(
            success=True,
            message="Seller statistics retrieved successfully",
            data={
                "total_assets": total_cars + total_properties,
                "total_products": total_products,
                "active_products": active_products,
                "out_of_stock_products": out_of_stock_products,
                "total_orders": total_orders,
                "pending_orders": pending_orders,
                "processing_orders": processing_orders,
                "paid_orders": paid_orders,
                "shipped_orders": shipped_orders,
                "delivered_orders": delivered_orders,
                "cancelled_orders": cancelled_orders,
                "total_revenue": float(gross_revenue),
                "net_revenue": float(net_revenue),
                "platform_fee_amount": float(platform_fee_amount),
                "range": range,
                "range_start": range_start.isoformat() if range_start else None,
                "range_end": range_end.isoformat(),
                "range_gross": float(range_gross),
                "kyc_status": seller_profile.kyc_status,
                "business_name": seller_profile.business_name,
                "recent_orders": recent_orders,
                "recent_products": recent_products,
                "total_inspections": total_inspections,
                "pending_inspections": pending_inspections,
                "total_agreements": total_agreements,
                "pending_agreements": pending_agreements,
                "active_agreements": active_agreements,
                "revenue_series": revenue_series,
                "orders_series": orders_series,
                "agreements_series": agreements_series,
                "alerts": alerts,
            },
        )
    except HTTPException:
        raise
    except Exception as e:
        log_error(
            seller_logger, f"Failed to fetch seller stats for user {user['id']}", e
        )
        raise HTTPException(status_code=500, detail="Failed to fetch seller statistics")


@router.get("/products", response_model=SellerProductsResponse)
async def get_seller_products(
    user=Depends(role_required(["seller", "admin"])),
    db: Session = Depends(get_db),
    page: int = Query(1, ge=1, description="Page number"),
    limit: int = Query(10, ge=1, le=100, description="Items per page"),
    status: Optional[str] = Query(None, description="Filter by product status"),
    search: Optional[str] = Query(None, description="Search products by name"),
):
    """Get seller's products with pagination and filtering"""
    try:
        seller_id = user["id"]
        offset = (page - 1) * limit

        # Build query for seller's products only
        query = (
            db.query(Product)
            .options(joinedload(Product.category), joinedload(Product.images))
            .filter(Product.seller_id == seller_id)
        )

        # Apply filters
        if status:
            query = query.filter(Product.status == status)

        if search:
            query = query.filter(Product.name.ilike(f"%{search}%"))

        # Get total count
        total_products = query.count()

        # Get paginated results
        products = (
            query.order_by(desc(Product.created_at)).offset(offset).limit(limit).all()
        )

        return SellerProductsResponse(
            success=True,
            message="Seller products retrieved successfully",
            data=[ProductResponse.model_validate(p) for p in products],
            pagination={
                "page": page,
                "limit": limit,
                "total": total_products,
                "total_pages": (total_products + limit - 1) // limit,
            },
        )
    except Exception as e:
        log_error(
            seller_logger, f"Failed to fetch seller products for user {user['id']}", e
        )
        raise HTTPException(status_code=500, detail="Failed to fetch seller products")


@router.get("/orders", response_model=SellerOrdersResponse)
async def get_seller_orders(
    user=Depends(role_required(["seller", "admin"])),
    db: Session = Depends(get_db),
    page: int = Query(1, ge=1, description="Page number"),
    limit: int = Query(10, ge=1, le=100, description="Items per page"),
    status_filter: Optional[OrderStatus] = Query(
        None, description="Filter by order status"
    ),
):
    """Get orders for seller's products"""
    try:
        seller_id = user["id"]
        status_value = status_filter.value if status_filter else None

        # Use the service method to get seller orders with proper filtering
        orders, total_orders = order_service.get_orders_by_seller(
            db, seller_id=seller_id, limit=limit, page=page, status=status_value
        )

        return SellerOrdersResponse(
            success=True,
            message="Seller orders retrieved successfully",
            data=[
                OrderResponse.model_validate(o).model_dump(by_alias=True)
                for o in orders
            ],
            pagination={
                "page": page,
                "limit": limit,
                "total": total_orders,
                "total_pages": (total_orders + limit - 1) // limit,
            },
        )
    except Exception as e:
        log_error(
            seller_logger, f"Failed to fetch seller orders for user {user['id']}", e
        )
        raise HTTPException(status_code=500, detail="Failed to fetch seller orders")


@router.get("/orders/{order_id}", response_model=OrderResponse)
async def get_seller_order_details(
    order_id: str,
    user=Depends(role_required(["seller", "admin"])),
    db: Session = Depends(get_db),
):
    """Get detailed information for a specific order containing seller's products"""
    try:
        seller_id = user["id"]

        # Use the service method to get seller order with proper filtering
        order = order_service.get_seller_order_by_id(db, order_id, seller_id)

        if not order:
            raise HTTPException(
                status_code=404,
                detail="Order not found or does not contain your products",
            )

        return OrderResponse.model_validate(order).model_dump(by_alias=True)

    except HTTPException:
        raise
    except Exception as e:
        log_error(
            seller_logger,
            f"Failed to fetch seller order details for order {order_id}",
            e,
        )
        raise HTTPException(status_code=500, detail="Failed to fetch order details")


@router.get("/analytics", response_model=SellerAnalyticsResponse)
async def get_seller_analytics(
    user=Depends(role_required(["seller", "admin"])),
    db: Session = Depends(get_db),
    period: str = Query("30d", description="Analytics period: 7d, 30d, 90d, 1y"),
):
    """Get comprehensive seller analytics data"""
    try:
        seller_id = user["id"]

        # Calculate date range based on period
        now = datetime.utcnow()

        if period == "7d":
            start_date = now - timedelta(days=7)
            prev_start_date = now - timedelta(days=14)
        elif period == "30d":
            start_date = now - timedelta(days=30)
            prev_start_date = now - timedelta(days=60)
        elif period == "90d":
            start_date = now - timedelta(days=90)
            prev_start_date = now - timedelta(days=180)
        elif period == "1y":
            start_date = now - timedelta(days=365)
            prev_start_date = now - timedelta(days=730)
        else:
            start_date = now - timedelta(days=30)
            prev_start_date = now - timedelta(days=60)

        # 1. Revenue analytics with order count - using seller earnings (after platform fee)
        revenue_query = (
            db.query(
                func.date(Order.created_at).label("date"),
                func.sum(
                    (OrderItem.quantity * OrderItem.price)
                    * 0.95  # 5% platform fee deducted
                ).label("revenue"),
                func.count(func.distinct(Order.id)).label("orders"),
            )
            .join(OrderItem)
            .join(Product)
            .filter(
                Product.seller_id == seller_id,
                Order.created_at >= start_date,
                Order.status.in_(["delivered", "shipped", "paid", "processing"]),
            )
        )

        revenue_data = (
            revenue_query.group_by(func.date(Order.created_at)).order_by("date").all()
        )

        # 2. Order analytics with total value - using seller earnings
        order_query = (
            db.query(
                func.date(Order.created_at).label("date"),
                func.count(func.distinct(Order.id)).label("orders"),
                func.sum(
                    (OrderItem.quantity * OrderItem.price)
                    * 0.95  # 5% platform fee deducted
                ).label("total_value"),
            )
            .join(OrderItem)
            .join(Product)
            .filter(Product.seller_id == seller_id, Order.created_at >= start_date)
        )

        order_data = (
            order_query.group_by(func.date(Order.created_at)).order_by("date").all()
        )

        # 3. Top selling products with stock info - using seller earnings
        top_products_query = (
            db.query(
                Product.id,
                Product.name,
                Product.stock_quantity,
                func.sum(OrderItem.quantity).label("total_sold"),
                func.sum(
                    (OrderItem.quantity * OrderItem.price)
                    * 0.95  # 5% platform fee deducted
                ).label("revenue"),
            )
            .join(OrderItem)
            .join(Order)
            .filter(
                Product.seller_id == seller_id,
                Order.created_at >= start_date,
                Order.status.in_(["delivered", "shipped", "paid", "processing"]),
            )
        )

        top_products = (
            top_products_query.group_by(
                Product.id, Product.name, Product.stock_quantity
            )
            .limit(10)
            .all()
        )

        # 4. Product performance (for products with orders) - using seller earnings
        product_performance_query = (
            db.query(
                Product.id,
                Product.name,
                func.sum(OrderItem.quantity).label("orders"),
                func.sum(
                    (OrderItem.quantity * OrderItem.price)
                    * 0.95  # 5% platform fee deducted
                ).label("revenue"),
            )
            .join(OrderItem)
            .join(Order)
            .filter(Product.seller_id == seller_id, Order.created_at >= start_date)
        )

        product_performance = (
            product_performance_query.group_by(Product.id, Product.name)
            .order_by(desc("revenue"))
            .limit(20)
            .all()
        )

        # 5. Customer insights - calculate correct average order value
        customer_stats_query = (
            db.query(
                func.count(func.distinct(Order.buyer_id)).label("total_customers"),
                func.avg(
                    (OrderItem.quantity * OrderItem.price)
                    * 0.95  # 5% platform fee deducted
                ).label("avg_order_value"),
            )
            .join(OrderItem)
            .join(Product)
            .filter(Product.seller_id == seller_id, Order.created_at >= start_date)
        )

        customer_stats = customer_stats_query.first()

        # Repeat customers
        repeat_customers_query = (
            db.query(Order.buyer_id)
            .join(OrderItem)
            .join(Product)
            .filter(Product.seller_id == seller_id, Order.created_at >= start_date)
        )

        repeat_customers = (
            db.query(func.count().label("repeat_count"))
            .select_from(
                repeat_customers_query.group_by(Order.buyer_id)
                .having(func.count(Order.id) > 1)
                .subquery()
            )
            .scalar()
            or 0
        )

        # 6. Inventory insights
        inventory_query = db.query(
            func.count(Product.id).label("total_products"),
            func.count(case((Product.stock_quantity > 0, Product.id))).label(
                "active_products"
            ),
            func.count(case((Product.stock_quantity == 0, Product.id))).label(
                "out_of_stock"
            ),
            func.count(case((Product.stock_quantity <= 5, Product.id))).label(
                "low_stock"
            ),
            func.sum(Product.stock_quantity * Product.price).label("inventory_value"),
        ).filter(Product.seller_id == seller_id)

        inventory_stats = inventory_query.first()

        # 7. Calculate growth metrics
        current_revenue = sum(r.revenue or 0 for r in revenue_data)

        # Calculate total orders for the period (all orders, not just revenue-generating ones)
        total_orders_query = (
            db.query(func.count(func.distinct(Order.id)))
            .join(OrderItem)
            .join(Product)
            .filter(Product.seller_id == seller_id, Order.created_at >= start_date)
        )
        current_orders = total_orders_query.scalar() or 0

        # Previous period metrics for growth calculation - using seller earnings
        prev_revenue_query = (
            db.query(
                func.sum(
                    (OrderItem.quantity * OrderItem.price)
                    * 0.95  # 5% platform fee deducted
                )
            )
            .join(Order)
            .join(Product)
            .filter(
                Product.seller_id == seller_id,
                Order.created_at >= prev_start_date,
                Order.created_at < start_date,
                Order.status.in_(["delivered", "shipped", "paid", "processing"]),
            )
        )

        prev_revenue = prev_revenue_query.scalar() or 0

        prev_orders_query = (
            db.query(func.count(func.distinct(Order.id)))
            .join(OrderItem)
            .join(Product)
            .filter(
                Product.seller_id == seller_id,
                Order.created_at >= prev_start_date,
                Order.created_at < start_date,
            )
        )

        prev_orders = prev_orders_query.scalar() or 0

        # Calculate growth percentages
        revenue_growth = (
            ((current_revenue - prev_revenue) / prev_revenue * 100)
            if prev_revenue > 0
            else 0
        )
        order_growth = (
            ((current_orders - prev_orders) / prev_orders * 100)
            if prev_orders > 0
            else 0
        )

        # Calculate repeat rate
        total_customers = customer_stats.total_customers or 0
        repeat_rate = (
            (repeat_customers / total_customers * 100) if total_customers > 0 else 0
        )

        return SellerAnalyticsResponse(
            success=True,
            message="Seller analytics retrieved successfully",
            data={
                # Time series data
                "revenue_data": [
                    {
                        "date": str(r.date),
                        "revenue": float(r.revenue or 0),
                        "orders": int(r.orders or 0),
                    }
                    for r in revenue_data
                ],
                "order_data": [
                    {
                        "date": str(o.date),
                        "orders": int(o.orders or 0),
                        "total_value": float(o.total_value or 0),
                    }
                    for o in order_data
                ],
                # Product insights
                "top_products": [
                    {
                        "id": str(p.id),
                        "name": p.name,
                        "total_sold": int(p.total_sold or 0),
                        "revenue": float(p.revenue or 0),
                        "stock_quantity": int(p.stock_quantity or 0),
                    }
                    for p in top_products
                ],
                "product_performance": [
                    {
                        "id": str(p.id),
                        "name": p.name,
                        "views": 0,  # TODO: Implement view tracking
                        "orders": int(p.orders or 0),
                        "conversion_rate": 0.0,  # TODO: Calculate conversion rate
                        "revenue": float(p.revenue or 0),
                    }
                    for p in product_performance
                ],
                # Customer insights
                "customer_insights": {
                    "total_customers": int(total_customers),
                    "repeat_customers": int(repeat_customers),
                    "repeat_rate": float(repeat_rate),
                    "average_order_value": float(customer_stats.avg_order_value or 0),
                },
                # Inventory insights
                "inventory_insights": {
                    "total_products": int(inventory_stats.total_products or 0),
                    "active_products": int(inventory_stats.active_products or 0),
                    "low_stock_products": int(inventory_stats.low_stock or 0),
                    "out_of_stock_products": int(inventory_stats.out_of_stock or 0),
                    "total_inventory_value": float(
                        inventory_stats.inventory_value or 0
                    ),
                },
                # Summary metrics
                "total_revenue": float(current_revenue),
                "total_orders": int(current_orders),
                "average_order_value": float(customer_stats.avg_order_value or 0),
                "revenue_growth": float(revenue_growth),
                "order_growth": float(order_growth),
                # Period info
                "period": period,
                "start_date": start_date.strftime("%Y-%m-%d"),
                "end_date": now.strftime("%Y-%m-%d"),
            },
        )
    except Exception as e:
        log_error(
            seller_logger, f"Failed to fetch seller analytics for user {user['id']}", e
        )
        raise HTTPException(status_code=500, detail="Failed to fetch seller analytics")


@router.patch("/orders/{order_id}/status", response_model=OrderStatusResponse)
async def update_seller_order_status(
    order_id: str,
    payload: OrderStatusUpdate,
    user=Depends(role_required(["seller", "admin"])),
    db: Session = Depends(get_db),
):
    """Update order status for seller's items only (seller-specific endpoint)"""
    try:
        system_settings_service.require_verified_email_for_user(
            db, user["id"], "manage seller orders"
        )
        seller_logger.info(
            f"Seller {user['id']} updating order {order_id} status to {payload.status}"
        )

        # Check if order exists and seller has items in it
        order = order_service.get_seller_order_by_id(
            db, UUID(order_id), UUID(user["id"])
        )
        if not order:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Order not found or you don't have items in this order",
            )

        # Check if we have the new item-level status system
        try:
            if hasattr(order.order_items[0], "status") and len(order.order_items) > 0:
                # Use new seller-specific item status update
                result = order_service.update_seller_items_status(
                    db=db,
                    order_id=UUID(order_id),
                    seller_id=UUID(user["id"]),
                    new_status=payload.status.value,
                    notes=payload.notes,
                )

                seller_logger.info(
                    f"Updated {result['seller_items_updated']} items to {result['seller_items_status']}"
                )

                return OrderStatusResponse(
                    success=True,
                    message=f"Updated {result['seller_items_updated']} of your items to {result['seller_items_status']}",
                    data=result,
                )
            else:
                # Fallback: Update entire order (temporary)
                result = order_service.update_order_status(
                    db=db,
                    order_id=UUID(order_id),
                    new_status=payload.status.value,
                    user_id=user["id"],
                    user_role="seller",
                    notes=payload.notes,
                )

                return OrderStatusResponse(
                    success=True,
                    message=f"Order status updated to {payload.status.value}",
                    data=result,
                )

        except (AttributeError, IndexError):
            # Fallback for database without status column
            result = order_service.update_order_status(
                db=db,
                order_id=UUID(order_id),
                new_status=payload.status.value,
                user_id=user["id"],
                user_role="seller",
                notes=payload.notes,
            )

            return OrderStatusResponse(
                success=True,
                message=f"Order status updated to {payload.status.value}",
                data=result,
            )

    except HTTPException:
        raise
    except Exception as e:
        seller_logger.error(f"Failed to update order status: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to update order status",
        )
