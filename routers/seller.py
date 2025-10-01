from fastapi import APIRouter, Depends, HTTPException, status, Query
from sqlalchemy.orm import Session, joinedload
from sqlalchemy import func, desc, case
from typing import Optional, List
from uuid import UUID

from db.session import get_db
from core.auth import role_required, get_current_user
from core.model import User, Profile, SellerProfile, Product, Order, OrderItem, ProductImage, Category
from schemas.products import ProductResponse, ProductCreate, ProductUpdate
from schemas.order import OrderResponse, OrderStatus, OrderStatusUpdate, OrderStatusResponse
from schemas.seller import (
    SellerProfileResponse, 
    SellerProfileUpdate, 
    SellerStatsResponse,
    SellerProductsResponse,
    SellerOrdersResponse,
    SellerAnalyticsResponse
)
from schemas.seller_payout import (
    SellerPayoutCreate, SellerPayoutResponse, SellerPayoutListResponse,
    SellerBalanceResponse, SellerBalanceData, PayoutRequestResponse
)
from core.seller_payout_service import seller_payout_service
from core.logging_config import get_logger, log_error
from core.order import OrderService
from copy import deepcopy

# Get logger for seller routes
seller_logger = get_logger("routers.seller")

# Initialize order service
order_service = OrderService()
router = APIRouter()

def calculate_seller_item_status(order, seller_id: str) -> str:
    """
    Calculate seller item status using the same logic as seller orders page
    """
    if not order.order_items:
        return "pending"
    
    # Get all sellers in this order to understand multi-vendor context
    all_sellers = set()
    for item in order.order_items:
        if item.product and item.product.seller_id:
            all_sellers.add(str(item.product.seller_id))
    
    current_seller_id_str = str(seller_id)
    overall_status = order.status
    
    # Determine seller's individual status based on order progression
    if overall_status == "pending":
        return "pending"
    elif overall_status == "processing":
        return "processing"
    elif overall_status == "shipped":
        # All sellers have shipped
        return "shipped"
    elif overall_status == "delivered":
        # All sellers have delivered
        return "delivered"
    elif overall_status == "cancelled":
        return "cancelled"
    elif overall_status == "partially_shipped":
        seller_index = list(all_sellers).index(current_seller_id_str) if current_seller_id_str in all_sellers else 0
        if seller_index % 2 == 0:
            # Even indexed sellers have shipped
            return "shipped"
        else:
            # Odd indexed sellers are still processing
            return "processing"
    elif overall_status == "partially_delivered":
        # Some sellers delivered, some didn't
        seller_index = list(all_sellers).index(current_seller_id_str) if current_seller_id_str in all_sellers else 0
        if seller_index % 3 == 0:
            # Every 3rd seller has delivered
            return "delivered"
        elif seller_index % 3 == 1:
            # Next seller has shipped but not delivered
            return "shipped"
        else:
            # Remaining sellers are still processing
            return "processing"
    elif overall_status == "partially_cancelled":
        # Some sellers cancelled, assume this seller is still active
        return "processing"
    else:
        return "processing"


# NOTE: Profile management (GET/PUT /profile) has been moved to /auth/me
# This eliminates code duplication and provides a unified API for all user types
# Use /auth/me for profile operations instead of /seller/profile


@router.get("/stats", response_model=SellerStatsResponse)
async def get_seller_stats(
    user=Depends(role_required(["seller"])),
    db: Session = Depends(get_db)
):
    """Get seller statistics"""
    try:
        seller_id = user["id"]
        
        # Get basic stats from seller profile
        seller_profile = (
            db.query(SellerProfile)
            .filter(SellerProfile.id == seller_id)
            .first()
        )
        
        if not seller_profile:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Seller profile not found"
            )
        
        # Get additional real-time stats
        total_products = (
            db.query(Product)
            .filter(Product.seller_id == seller_id)
            .count()
        )
        
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
        
        # Get order stats
        total_orders = (
            db.query(Order)
            .join(OrderItem)
            .join(Product)
            .filter(Product.seller_id == seller_id)
            .count()
        )
        
        pending_orders = (
            db.query(Order)
            .join(OrderItem)
            .join(Product)
            .filter(Product.seller_id == seller_id, Order.status == "processing")
            .count()
        )
        
        # Get revenue (sum of order items for this seller)
        revenue_result = (
            db.query(func.sum(OrderItem.quantity * OrderItem.price))
            .join(Product)
            .join(Order)
            .filter(Product.seller_id == seller_id, Order.status == "delivered")
            .scalar()
        )
        
        total_revenue = float(revenue_result) if revenue_result else 0.0
        
        # Get recent orders (last 5)
        recent_orders_query = (
            db.query(Order)
            .join(OrderItem)
            .join(Product)
            .filter(Product.seller_id == seller_id)
            .options(joinedload(Order.buyer).joinedload(Profile.user))
            .order_by(desc(Order.created_at))
            .limit(5)
        )
        
        recent_orders = []
        for order in recent_orders_query.all():
            # Count items for this seller in this order
            seller_items = (
                db.query(OrderItem)
                .join(Product)
                .filter(Product.seller_id == seller_id, OrderItem.order_id == order.id)
                .count()
            )
            
            # Calculate total amount for this seller's items in this order
            seller_amount = (
                db.query(func.sum(OrderItem.quantity * OrderItem.price))
                .join(Product)
                .filter(Product.seller_id == seller_id, OrderItem.order_id == order.id)
                .scalar()
            ) or 0
            
            # Calculate seller_item_status using the same logic as seller orders page
            seller_item_status = calculate_seller_item_status(order, seller_id)
            
            recent_orders.append({
                "id": str(order.id),
                "status": order.status,  # Keep original status
                "seller_item_status": seller_item_status,  # Add calculated seller status
                "total_amount": float(seller_amount),
                "created_at": order.created_at.isoformat(),
                "buyer": {
                    "email": order.buyer.user.email if order.buyer and order.buyer.user else None
                },
                "order_items": [{"length": seller_items}]  # For compatibility
            })
        
        # Get recent products (last 3)
        recent_products_query = (
            db.query(Product)
            .filter(Product.seller_id == seller_id)
            .order_by(desc(Product.created_at))
            .limit(3)
        )
        
        recent_products = []
        for product in recent_products_query.all():
            recent_products.append({
                "id": str(product.id),
                "name": product.name,
                "price": float(product.price),
                "stock_quantity": product.stock_quantity,
                "status": product.status
            })
        
        return SellerStatsResponse(
            success=True,
            message="Seller statistics retrieved successfully",
            data={
                "total_products": total_products,
                "active_products": active_products,
                "out_of_stock_products": out_of_stock_products,
                "total_orders": total_orders,
                "pending_orders": pending_orders,
                "total_revenue": total_revenue,
                "kyc_status": seller_profile.kyc_status,
                "business_name": seller_profile.business_name,
                "recent_orders": recent_orders,
                "recent_products": recent_products,
                "revenue_trend": "+12%",  # TODO: Calculate from historical data
                "orders_trend": "+5%"     # TODO: Calculate from historical data
            }
        )
    except HTTPException:
        raise
    except Exception as e:
        log_error(seller_logger, f"Failed to fetch seller stats for user {user['id']}", e)
        raise HTTPException(status_code=500, detail="Failed to fetch seller statistics")


@router.get("/products", response_model=SellerProductsResponse)
async def get_seller_products(
    user=Depends(role_required(["seller"])),
    db: Session = Depends(get_db),
    page: int = Query(1, ge=1, description="Page number"),
    limit: int = Query(10, ge=1, le=100, description="Items per page"),
    status: Optional[str] = Query(None, description="Filter by product status"),
    search: Optional[str] = Query(None, description="Search products by name")
):
    """Get seller's products with pagination and filtering"""
    try:
        seller_id = user["id"]
        offset = (page - 1) * limit
        
        # Build query for seller's products only
        query = (
            db.query(Product)
            .options(
                joinedload(Product.category),
                joinedload(Product.images)
            )
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
            query
            .order_by(desc(Product.created_at))
            .offset(offset)
            .limit(limit)
            .all()
        )
        
        return SellerProductsResponse(
            success=True,
            message="Seller products retrieved successfully",
            data=[ProductResponse.model_validate(p) for p in products],
            pagination={
                "page": page,
                "limit": limit,
                "total": total_products,
                "total_pages": (total_products + limit - 1) // limit
            }
        )
    except Exception as e:
        log_error(seller_logger, f"Failed to fetch seller products for user {user['id']}", e)
        raise HTTPException(status_code=500, detail="Failed to fetch seller products")


@router.get("/orders", response_model=SellerOrdersResponse)
async def get_seller_orders(
    user=Depends(role_required(["seller"])),
    db: Session = Depends(get_db),
    page: int = Query(1, ge=1, description="Page number"),
    limit: int = Query(10, ge=1, le=100, description="Items per page"),
    status_filter: Optional[OrderStatus] = Query(None, description="Filter by order status")
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
            data=[OrderResponse.model_validate(o).model_dump(by_alias=True) for o in orders],
            pagination={
                "page": page,
                "limit": limit,
                "total": total_orders,
                "total_pages": (total_orders + limit - 1) // limit
            }
        )
    except Exception as e:
        log_error(seller_logger, f"Failed to fetch seller orders for user {user['id']}", e)
        raise HTTPException(status_code=500, detail="Failed to fetch seller orders")


@router.get("/orders/{order_id}", response_model=OrderResponse)
async def get_seller_order_details(
    order_id: str,
    user=Depends(role_required(["seller"])),
    db: Session = Depends(get_db)
):
    """Get detailed information for a specific order containing seller's products"""
    try:
        seller_id = user["id"]
        
        # Use the service method to get seller order with proper filtering
        order = order_service.get_seller_order_by_id(db, order_id, seller_id)
        
        if not order:
            raise HTTPException(
                status_code=404, 
                detail="Order not found or does not contain your products"
            )
        
        return OrderResponse.model_validate(order).model_dump(by_alias=True)
        
    except HTTPException:
        raise
    except Exception as e:
        log_error(seller_logger, f"Failed to fetch seller order details for order {order_id}", e)
        raise HTTPException(status_code=500, detail="Failed to fetch order details")


@router.get("/analytics", response_model=SellerAnalyticsResponse)
async def get_seller_analytics(
    user=Depends(role_required(["seller"])),
    db: Session = Depends(get_db),
    period: str = Query("30d", description="Analytics period: 7d, 30d, 90d, 1y")
):
    """Get comprehensive seller analytics data"""
    try:
        seller_id = user["id"]
        
        # Calculate date range based on period
        from datetime import datetime, timedelta
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
        
        # 1. Revenue analytics with order count
        revenue_query = (
            db.query(
                func.date(Order.created_at).label('date'),
                func.sum(OrderItem.quantity * OrderItem.price).label('revenue'),
                func.count(func.distinct(Order.id)).label('orders')
            )
            .join(OrderItem)
            .join(Product)
            .filter(
                Product.seller_id == seller_id,
                Order.created_at >= start_date,
                Order.status.in_(["delivered", "shipped", "processing"])
            )
        )
        
        revenue_data = (
            revenue_query
            .group_by(func.date(Order.created_at))
            .order_by('date')
            .all()
        )
        
        # 2. Order analytics with total value
        order_query = (
            db.query(
                func.date(Order.created_at).label('date'),
                func.count(func.distinct(Order.id)).label('orders'),
                func.sum(OrderItem.quantity * OrderItem.price).label('total_value')
            )
            .join(OrderItem)
            .join(Product)
            .filter(
                Product.seller_id == seller_id,
                Order.created_at >= start_date
            )
        )
        
        order_data = (
            order_query
            .group_by(func.date(Order.created_at))
            .order_by('date')
            .all()
        )
        
        # 3. Top selling products with stock info
        top_products_query = (
            db.query(
                Product.id,
                Product.name,
                Product.stock_quantity,
                func.sum(OrderItem.quantity).label('total_sold'),
                func.sum(OrderItem.quantity * OrderItem.price).label('revenue')
            )
            .join(OrderItem)
            .join(Order)
            .filter(
                Product.seller_id == seller_id,
                Order.created_at >= start_date,
                Order.status.in_(["delivered", "shipped", "processing"])
            )
        )
        
        top_products = (
            top_products_query
            .group_by(Product.id, Product.name, Product.stock_quantity)
            .limit(10)
            .all()
        )
        
        # 4. Product performance (for products with orders)
        product_performance_query = (
            db.query(
                Product.id,
                Product.name,
                func.sum(OrderItem.quantity).label('orders'),
                func.sum(OrderItem.quantity * OrderItem.price).label('revenue')
            )
            .join(OrderItem)
            .join(Order)
            .filter(
                Product.seller_id == seller_id,
                Order.created_at >= start_date
            )
        )
        
        product_performance = (
            product_performance_query
            .group_by(Product.id, Product.name)
            .order_by(desc('revenue'))
            .limit(20)
            .all()
        )
        
        # 5. Customer insights
        customer_stats_query = (
            db.query(
                func.count(func.distinct(Order.buyer_id)).label('total_customers'),
                func.avg(OrderItem.quantity * OrderItem.price).label('avg_order_value')
            )
            .join(OrderItem)
            .join(Product)
            .filter(
                Product.seller_id == seller_id,
                Order.created_at >= start_date
            )
        )
        
        customer_stats = customer_stats_query.first()
        
        # Repeat customers
        repeat_customers_query = (
            db.query(Order.buyer_id)
            .join(OrderItem)
            .join(Product)
            .filter(
                Product.seller_id == seller_id,
                Order.created_at >= start_date
            )
        )
        
        repeat_customers = (
            db.query(func.count().label('repeat_count'))
            .select_from(
                repeat_customers_query
                .group_by(Order.buyer_id)
                .having(func.count(Order.id) > 1)
                .subquery()
            )
            .scalar() or 0
        )
        
        # 6. Inventory insights
        inventory_query = (
            db.query(
                func.count(Product.id).label('total_products'),
                func.count(case((Product.stock_quantity > 0, Product.id))).label('active_products'),
                func.count(case((Product.stock_quantity == 0, Product.id))).label('out_of_stock'),
                func.count(case((Product.stock_quantity <= 5, Product.id))).label('low_stock'),
                func.sum(Product.stock_quantity * Product.price).label('inventory_value')
            )
            .filter(Product.seller_id == seller_id)
        )
        
        inventory_stats = inventory_query.first()
        
        # 7. Calculate growth metrics
        current_revenue = sum(r.revenue or 0 for r in revenue_data)
        current_orders = sum(r.orders or 0 for r in revenue_data)
        
        # Previous period metrics for growth calculation
        prev_revenue_query = (
            db.query(func.sum(OrderItem.quantity * OrderItem.price))
            .join(Order)
            .join(Product)
            .filter(
                Product.seller_id == seller_id,
                Order.created_at >= prev_start_date,
                Order.created_at < start_date,
                Order.status.in_(["delivered", "shipped", "processing"])
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
                Order.created_at < start_date
            )
        )
        
        prev_orders = prev_orders_query.scalar() or 0
        
        # Calculate growth percentages
        revenue_growth = ((current_revenue - prev_revenue) / prev_revenue * 100) if prev_revenue > 0 else 0
        order_growth = ((current_orders - prev_orders) / prev_orders * 100) if prev_orders > 0 else 0
        
        # Calculate repeat rate
        total_customers = customer_stats.total_customers or 0
        repeat_rate = (repeat_customers / total_customers * 100) if total_customers > 0 else 0
        
        return SellerAnalyticsResponse(
            success=True,
            message="Seller analytics retrieved successfully",
            data={
                # Time series data
                "revenue_data": [
                    {
                        "date": str(r.date),
                        "revenue": float(r.revenue or 0),
                        "orders": int(r.orders or 0)
                    } for r in revenue_data
                ],
                "order_data": [
                    {
                        "date": str(o.date),
                        "orders": int(o.orders or 0),
                        "total_value": float(o.total_value or 0)
                    } for o in order_data
                ],
                
                # Product insights
                "top_products": [
                    {
                        "id": str(p.id),
                        "name": p.name,
                        "total_sold": int(p.total_sold or 0),
                        "revenue": float(p.revenue or 0),
                        "stock_quantity": int(p.stock_quantity or 0)
                    } for p in top_products
                ],
                "product_performance": [
                    {
                        "id": str(p.id),
                        "name": p.name,
                        "views": 0,  # TODO: Implement view tracking
                        "orders": int(p.orders or 0),
                        "conversion_rate": 0.0,  # TODO: Calculate conversion rate
                        "revenue": float(p.revenue or 0)
                    } for p in product_performance
                ],
                
                # Customer insights
                "customer_insights": {
                    "total_customers": int(total_customers),
                    "repeat_customers": int(repeat_customers),
                    "repeat_rate": float(repeat_rate),
                    "average_order_value": float(customer_stats.avg_order_value or 0)
                },
                
                # Inventory insights
                "inventory_insights": {
                    "total_products": int(inventory_stats.total_products or 0),
                    "active_products": int(inventory_stats.active_products or 0),
                    "low_stock_products": int(inventory_stats.low_stock or 0),
                    "out_of_stock_products": int(inventory_stats.out_of_stock or 0),
                    "total_inventory_value": float(inventory_stats.inventory_value or 0)
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
                "end_date": now.strftime("%Y-%m-%d")
            }
        )
    except Exception as e:
        log_error(seller_logger, f"Failed to fetch seller analytics for user {user['id']}", e)
        raise HTTPException(status_code=500, detail="Failed to fetch seller analytics")


@router.post("/kyc/submit")
async def submit_kyc_documents(
    user=Depends(role_required(["seller"])),
    db: Session = Depends(get_db)
):
    """Submit KYC documents for verification"""
    try:
        seller_profile = (
            db.query(SellerProfile)
            .filter(SellerProfile.id == user["id"])
            .first()
        )
        
        if not seller_profile:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Seller profile not found"
            )
        
        # Update KYC status to pending
        seller_profile.kyc_status = "pending"
        db.commit()
        
        return {
            "success": True,
            "message": "KYC documents submitted successfully. Verification is pending."
        }
    except HTTPException:
        raise
    except Exception as e:
        log_error(seller_logger, f"Failed to submit KYC for user {user['id']}", e)
        raise HTTPException(status_code=500, detail="Failed to submit KYC documents")


@router.patch("/orders/{order_id}/status", response_model=OrderStatusResponse)
async def update_seller_order_status(
    order_id: str,
    payload: OrderStatusUpdate,
    user=Depends(role_required(["seller"])),
    db: Session = Depends(get_db)
):
    """Update order status for seller's items only (seller-specific endpoint)"""
    try:
        seller_logger.info(f"Seller {user['id']} updating order {order_id} status to {payload.status}")
        
        # Check if order exists and seller has items in it
        order = order_service.get_seller_order_by_id(db, UUID(order_id), UUID(user["id"]))
        if not order:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Order not found or you don't have items in this order"
            )
        
        # Check if we have the new item-level status system
        try:
            if hasattr(order.order_items[0], 'status') and len(order.order_items) > 0:
                # Use new seller-specific item status update
                result = order_service.update_seller_items_status(
                    db=db,
                    order_id=UUID(order_id),
                    seller_id=UUID(user["id"]),
                    new_status=payload.status.value,
                    notes=payload.notes
                )
                
                seller_logger.info(f"Updated {result['seller_items_updated']} items to {result['seller_items_status']}")
                
                return OrderStatusResponse(
                    success=True,
                    message=f"Updated {result['seller_items_updated']} of your items to {result['seller_items_status']}",
                    data=result
                )
            else:
                # Fallback: Update entire order (temporary)
                result = order_service.update_order_status(
                    db=db,
                    order_id=UUID(order_id),
                    new_status=payload.status.value,
                    user_id=user["id"],
                    user_role="seller",
                    notes=payload.notes
                )
                
                return OrderStatusResponse(
                    success=True,
                    message=f"Order status updated to {payload.status.value}",
                    data=result
                )
                
        except (AttributeError, IndexError):
            # Fallback for database without status column
            result = order_service.update_order_status(
                db=db,
                order_id=UUID(order_id),
                new_status=payload.status.value,
                user_id=user["id"],
                user_role="seller",
                notes=payload.notes
            )
            
            return OrderStatusResponse(
                success=True,
                message=f"Order status updated to {payload.status.value}",
                data=result
            )
        
    except HTTPException:
        raise
    except Exception as e:
        seller_logger.error(f"Failed to update order status: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to update order status"
        )


# ---------------- SELLER PAYOUT ENDPOINTS ----------------

@router.get("/balance", response_model=SellerBalanceResponse)
async def get_seller_balance(
    user=Depends(role_required(["seller"])),
    db: Session = Depends(get_db)
):
    """Get seller balance and payout information"""
    try:
        seller_id = user["id"]
        
        seller = db.query(SellerProfile).filter(SellerProfile.id == seller_id).first()
        if not seller:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Seller profile not found"
            )
        
        balance_data = SellerBalanceData(
            available_balance=seller.available_balance,
            pending_balance=seller.pending_balance,
            total_paid=seller.total_paid,
            total_revenue=seller.total_revenue,
            platform_fee_rate=seller_payout_service.PLATFORM_FEE_RATE,
            payout_account_configured=bool(seller.payout_recipient_code)
        )
        
        return SellerBalanceResponse(
            success=True,
            message="Balance retrieved successfully",
            data=balance_data.model_dump()
        )
        
    except HTTPException:
        raise
    except Exception as e:
        seller_logger.error(f"Failed to get seller balance: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to retrieve balance"
        )

@router.post("/payouts", response_model=PayoutRequestResponse)
async def request_payout(
    payout_data: SellerPayoutCreate,
    user=Depends(role_required(["seller"])),
    db: Session = Depends(get_db)
):
    """Request a payout for seller earnings"""
    try:
        seller_id = user["id"]
        
        # Validate payout amount
        if payout_data.amount <= 0:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Payout amount must be greater than 0"
            )
        
        # Create payout request
        payout = seller_payout_service.create_payout(
            db=db,
            seller_id=seller_id,
            amount=payout_data.amount,
            account_number=payout_data.account_number,
            bank_code=payout_data.bank_code,
            bank_name=payout_data.bank_name
        )
        
        # Create notification for payout request
        from core.notifications_service import create_notification
        create_notification(db, {
            "user_id": str(seller_id),
            "type": "payment_successful",  # Using existing type
            "title": "Payout Requested",
            "message": f"Your payout request of ₦{payout_data.amount:,.2f} has been submitted and is being processed.",
            "priority": "medium",
            "channels": ["in_app"],
            "data": {
                "payout_id": str(payout.id),
                "amount": float(payout_data.amount),
                "status": "pending"
            }
        })
        
        return PayoutRequestResponse(
            success=True,
            message="Payout request submitted successfully",
            data=SellerPayoutResponse.model_validate(payout).model_dump()
        )
        
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e)
        )
    except HTTPException:
        raise
    except Exception as e:
        seller_logger.error(f"Failed to create payout request: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to create payout request"
        )

@router.get("/payouts", response_model=SellerPayoutListResponse)
async def get_seller_payouts(
    page: int = Query(1, ge=1, description="Page number"),
    limit: int = Query(20, ge=1, le=100, description="Items per page"),
    user=Depends(role_required(["seller"])),
    db: Session = Depends(get_db)
):
    """Get seller payout history"""
    try:
        seller_id = user["id"]
        
        payouts, total_count = seller_payout_service.get_seller_payouts(
            db=db,
            seller_id=seller_id,
            limit=limit,
            page=page
        )
        
        payout_responses = [
            SellerPayoutResponse.model_validate(payout).model_dump() 
            for payout in payouts
        ]
        
        total_pages = (total_count + limit - 1) // limit
        
        return SellerPayoutListResponse(
            success=True,
            message="Payouts retrieved successfully",
            data=payout_responses,
            pagination={
                "page": page,
                "limit": limit,
                "total_count": total_count,
                "total_pages": total_pages,
                "has_next": page < total_pages,
                "has_prev": page > 1
            }
        )
        
    except Exception as e:
        seller_logger.error(f"Failed to get seller payouts: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to retrieve payouts"
        )
