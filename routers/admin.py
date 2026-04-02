from fastapi import APIRouter, Depends, HTTPException, status, Query
from sqlalchemy.orm import Session, joinedload
from sqlalchemy import func, desc, and_, or_
from typing import Optional, List
from uuid import UUID
from datetime import datetime, timedelta
from decimal import Decimal

from db.session import get_db
from core.auth import role_required
from core.model import (
    User, Profile, SellerProfile, Product, Order, OrderItem, Category, 
    Payment, SellerPayout, GeneralInspection, GeneralAgreement,
    Property, RealEstateSessionRequest, PropertyUnit, CarUnit, PhoneUnit
)
from schemas.property import SessionRequestResponse, PropertyPublish, PropertyResponse
from schemas.admin import (
    AdminDashboardStats, AdminUserListResponse, AdminUserDetailResponse,
    AdminSellerListResponse, AdminProductListResponse, AdminOrderListResponse,
    AdminUserActionRequest, AdminSellerActionRequest, AdminProductActionRequest,
    AdminResponse, AdminListResponse, AdminUserListFilters,
    AdminSellerListFilters, AdminProductListFilters, AdminOrderListFilters
)
from core.property_service import property_service
from core.asset_service import asset_service
from core.logging_config import get_logger, log_error
from core.auth_service import auth_service
from core.notifications_service import create_notification
from core.seller_payout_service import seller_payout_service
from schemas.seller_payout import (
    AdminPayoutListResponse, AdminPayoutResponse, PayoutProcessRequest, PayoutProcessResponse
)
from pydantic import BaseModel, Field

from core.order import OrderService
from schemas.order import OrderStatusResponse


# Get logger for admin routes
admin_logger = get_logger("routers.admin")

router = APIRouter()


class CreateAdminRequest(BaseModel):
    email: str = Field(..., description="Admin email address")
    password: str = Field(..., min_length=8, description="Admin password")
    business_name: str = Field(..., min_length=2, description="Admin/Business name")
    description: str = Field(default="System Administrator", description="Admin description")


@router.post("/create-admin", response_model=AdminResponse)
async def create_admin_user(
    request: CreateAdminRequest,
    current_admin=Depends(role_required(["admin"])),
    db: Session = Depends(get_db)
):
    """Create a new admin user (only accessible by existing admins)"""
    try:
        admin_logger.info(f"Admin attempting to create admin: {request.email}")
        
        # Check if user already exists
        existing_user = db.query(User).filter(User.email == request.email).first()
        if existing_user:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"User with email {request.email} already exists"
            )
        
        # Create admin user
        user_id = auth_service.create_admin_user(
            db=db,
            email=request.email,
            password=request.password,
            business_name=request.business_name,
            description=request.description
        )
        
        admin_logger.info(f"Admin user created: {request.email} (ID: {user_id}) by")
        
        return AdminResponse(
            success=True,
            message=f"Admin user {request.email} created successfully",
            data={
                "user_id": user_id,
                "email": request.email,
                "business_name": request.business_name,
                "role": "admin",
                "created_by": current_admin['email']
            }
        )
        
    except HTTPException:
        raise
    except Exception as e:
        log_error(admin_logger, f"Failed to create admin user {request.email}", e)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to create admin user"
        )


@router.get("/dashboard/stats", response_model=AdminResponse)
async def get_admin_dashboard_stats(
    user=Depends(role_required(["admin"])),
    db: Session = Depends(get_db)
):
    """Get admin dashboard statistics"""
    try:
        # Basic counts
        total_users = db.query(User).count()
        total_products = db.query(Product).count()
        total_orders = db.query(Order).count()
        
        # Revenue calculation - include all paid orders (processing, shipped, delivered)
        total_revenue = (
            db.query(func.sum(OrderItem.quantity * OrderItem.price))
            .join(Order)
            .filter(Order.status.in_(["processing", "shipped", "delivered"]))
            .scalar() or 0
        )
        
        # Today's stats
        today = datetime.utcnow().date()
        new_users_today = (
            db.query(User)
            .filter(func.date(User.created_at) == today)
            .count()
        )
        
        new_orders_today = (
            db.query(Order)
            .filter(func.date(Order.created_at) == today)
            .count()
        )
        
        revenue_today = (
            db.query(func.sum(OrderItem.quantity * OrderItem.price))
            .join(Order)
            .filter(
                func.date(Order.created_at) == today,
                Order.status.in_(["processing", "shipped", "delivered"])
            )
            .scalar() or 0
        )
        
        # Status counts
        pending_seller_approvals = (
            db.query(SellerProfile)
            .filter(SellerProfile.kyc_status == "pending")
            .count()
        )
        
        locked_users = (
            db.query(User)
            .filter(User.locked_until > datetime.utcnow())
            .count()
        )
        
        out_of_stock_products = (
            db.query(Product)
            .filter(Product.stock_quantity == 0)
            .count()
        )
        
        pending_orders = (
            db.query(Order)
            .filter(Order.status == "pending")
            .count()
        )
        
        total_payments = (
            db.query(Payment)
            .filter(Payment.status == "completed")
            .count()
        )
        
        # Asset stats
        total_inspections = db.query(GeneralInspection).count()
        total_agreements = db.query(GeneralAgreement).count()
        pending_inspections = db.query(GeneralInspection).filter(GeneralInspection.status == "scheduled").count()
        pending_agreements = db.query(GeneralAgreement).filter(GeneralAgreement.status == "pending_review").count()
        active_agreements = db.query(GeneralAgreement).filter(GeneralAgreement.status == "active").count()
        
        # Real Estate stats
        total_session_requests = db.query(RealEstateSessionRequest).count()
        pending_session_requests = db.query(RealEstateSessionRequest).filter(RealEstateSessionRequest.status == "pending").count()
        total_internal_properties = db.query(Property).filter(Property.title.ilike("[ACQUIRED]%")).count()
        
        stats = AdminDashboardStats(
            total_users=total_users,
            total_products=total_products,
            total_orders=total_orders,
            total_payments=total_payments,  # Actual payment count
            total_revenue=float(total_revenue),
            new_users_today=new_users_today,
            new_orders_today=new_orders_today,
            revenue_today=float(revenue_today),
            pending_seller_approvals=pending_seller_approvals,
            locked_users=locked_users,
            out_of_stock_products=out_of_stock_products,
            pending_orders=pending_orders,
            
            # New asset stats
            total_inspections=total_inspections,
            total_agreements=total_agreements,
            pending_inspections=pending_inspections,
            pending_agreements=pending_agreements,
            active_agreements=active_agreements,
            
            # Real Estate stats
            total_session_requests=total_session_requests,
            pending_session_requests=pending_session_requests,
            total_internal_properties=total_internal_properties
        )
        
        return AdminResponse(
            success=True,
            message="Admin dashboard stats retrieved successfully",
            data=stats.dict()
        )
        
    except Exception as e:
        log_error(admin_logger, f"Failed to fetch admin dashboard stats", e)
        raise HTTPException(status_code=500, detail="Failed to fetch dashboard stats")


@router.get("/analytics/order-status", response_model=AdminResponse)
async def get_admin_order_status_analytics(
    user=Depends(role_required(["admin"])),
    db: Session = Depends(get_db)
):
    """Get order status breakdown for admin analytics"""
    try:
        # Order status counts
        order_status_counts = (
            db.query(
                Order.status,
                func.count(Order.id).label('count')
            )
            .group_by(Order.status)
            .all()
        )
        
        # Convert to dictionary for easier access
        status_breakdown = {status: count for status, count in order_status_counts}
        
        # Calculate percentages
        total_orders = sum(status_breakdown.values())
        status_percentages = {
            status: (count / total_orders * 100) if total_orders > 0 else 0
            for status, count in status_breakdown.items()
        }
        
        return AdminResponse(
            success=True,
            message="Order status analytics retrieved successfully",
            data={
                "status_breakdown": status_breakdown,
                "status_percentages": status_percentages,
                "total_orders": total_orders
            }
        )
        
    except Exception as e:
        log_error(admin_logger, f"Failed to fetch order status analytics", e)
        raise HTTPException(status_code=500, detail="Failed to fetch order status analytics")


@router.get("/users", response_model=AdminListResponse)
async def get_admin_users(
    user=Depends(role_required(["admin"])),
    db: Session = Depends(get_db),
    role: Optional[str] = Query(None),
    email_verified: Optional[bool] = Query(None),
    is_locked: Optional[bool] = Query(None),
    search: Optional[str] = Query(None),
    page: int = Query(1, ge=1),
    limit: int = Query(20, ge=1, le=100)
):
    """Get users list for admin management"""
    try:
        offset = (page - 1) * limit
        
        # Build query
        query = (
            db.query(User)
            .outerjoin(Profile)
            .outerjoin(SellerProfile)
        )
        
        # Apply filters
        if role:
            query = query.filter(User.role == role)
        
        if email_verified is not None:
            query = query.filter(User.email_verified == email_verified)
        
        if is_locked is not None:
            if is_locked:
                query = query.filter(User.locked_until > datetime.utcnow())
            else:
                query = query.filter(
                    or_(User.locked_until.is_(None), User.locked_until <= datetime.utcnow())
                )
        
        if search:
            query = query.filter(
                or_(
                    User.email.ilike(f"%{search}%"),
                    Profile.name.ilike(f"%{search}%"),
                    SellerProfile.business_name.ilike(f"%{search}%")
                )
            )
        
        # Get total count
        total_users = query.count()
        
        # Get paginated results
        users = (
            query
            .order_by(desc(User.created_at))
            .offset(offset)
            .limit(limit)
            .all()
        )
        
        # Format response
        user_list = []
        for user_obj in users:
            profile_name = None
            if user_obj.role == "customer" and user_obj.profile:
                profile_name = user_obj.profile.name
            elif user_obj.role == "seller" and user_obj.seller_profile:
                profile_name = user_obj.seller_profile.business_name
            
            user_data = AdminUserListResponse(
                id=user_obj.id,
                email=user_obj.email,
                role=user_obj.role,
                email_verified=user_obj.email_verified,
                email_verified_at=user_obj.email_verified_at,
                failed_login_attempts=user_obj.failed_login_attempts,
                locked_until=user_obj.locked_until,
                last_login=user_obj.last_login,
                created_at=user_obj.created_at,
                updated_at=user_obj.updated_at,
                profile_name=profile_name
            )
            user_list.append(user_data.dict())
        
        return AdminListResponse(
            success=True,
            message="Users retrieved successfully",
            data=user_list,
            pagination={
                "page": page,
                "limit": limit,
                "total_pages": (total_users + limit - 1) // limit,
                "has_next": page * limit < total_users,
                "has_prev": page > 1
            },
            total=total_users
        )
        
    except Exception as e:
        log_error(admin_logger, f"Failed to fetch users list", e)
        raise HTTPException(status_code=500, detail="Failed to fetch users")


@router.get("/sellers", response_model=AdminListResponse)
async def get_admin_sellers(
    user=Depends(role_required(["admin"])),
    db: Session = Depends(get_db),
    kyc_status: Optional[str] = Query(None),
    is_locked: Optional[bool] = Query(None),
    search: Optional[str] = Query(None),
    page: int = Query(1, ge=1),
    limit: int = Query(20, ge=1, le=100)
):
    """Get sellers list for admin management"""
    try:
        offset = (page - 1) * limit
        
        # Build query
        query = (
            db.query(SellerProfile)
            .join(User)
            .options(joinedload(SellerProfile.user))
        )
        
        # Apply filters
        if kyc_status:
            query = query.filter(SellerProfile.kyc_status == kyc_status)
        
        if is_locked is not None:
            if is_locked:
                query = query.filter(User.locked_until > datetime.utcnow())
            else:
                query = query.filter(
                    or_(User.locked_until.is_(None), User.locked_until <= datetime.utcnow())
                )
        
        if search:
            query = query.filter(
                or_(
                    SellerProfile.business_name.ilike(f"%{search}%"),
                    User.email.ilike(f"%{search}%")
                )
            )
        
        # Get total count
        total_sellers = query.count()
        
        # Get paginated results
        sellers = (
            query
            .order_by(desc(SellerProfile.created_at))
            .offset(offset)
            .limit(limit)
            .all()
        )
        
        # Format response
        seller_list = []
        for seller in sellers:
            seller_data = AdminSellerListResponse(
                id=seller.id,
                email=seller.user.email,
                business_name=seller.business_name,
                seller_type=seller.seller_type,
                description=seller.description,
                contact_email=seller.contact_email,
                contact_phone=seller.contact_phone,
                website_url=seller.website_url,
                kyc_status=seller.kyc_status,
                approval_date=seller.approval_date,
                total_products=seller.total_products,
                total_orders=seller.total_orders,
                total_revenue=seller.total_revenue,
                available_balance=seller.available_balance or Decimal('0.00'),
                pending_balance=seller.pending_balance or Decimal('0.00'),
                created_at=seller.created_at,
                updated_at=seller.updated_at,
                user_locked=seller.user.locked_until
            )
            seller_list.append(seller_data.dict())
        
        return AdminListResponse(
            success=True,
            message="Sellers retrieved successfully",
            data=seller_list,
            pagination={
                "page": page,
                "limit": limit,
                "total_pages": (total_sellers + limit - 1) // limit,
                "has_next": page * limit < total_sellers,
                "has_prev": page > 1
            },
            total=total_sellers
        )
        
    except Exception as e:
        log_error(admin_logger, f"Failed to fetch sellers list", e)
        raise HTTPException(status_code=500, detail="Failed to fetch sellers")


@router.patch("/sellers/{seller_id}/kyc", response_model=AdminResponse)
async def update_seller_kyc_status(
    seller_id: UUID,
    action: AdminSellerActionRequest,
    user=Depends(role_required(["admin"])),
    db: Session = Depends(get_db)
):
    """Approve or reject seller KYC"""
    try:
        seller = db.query(SellerProfile).filter(SellerProfile.id == seller_id).first()
        if not seller:
            raise HTTPException(status_code=404, detail="Seller not found")
        
        if action.action == "approve_kyc":
            seller.kyc_status = "approved"
            seller.approval_date = datetime.utcnow().date()
            message = "Seller KYC approved successfully"
            
            # Create notification for KYC approval
            try:
                create_notification(db, {
                    "user_id": str(seller.id),
                    "type": "account_verified",
                    "title": "KYC Approved!",
                    "message": f"Congratulations! Your KYC verification has been approved. You can now start selling on our platform.",
                    "priority": "high",
                    "channels": ["in_app", "email"],
                    "data": {
                        "seller_id": str(seller.id),
                        "kyc_status": "approved",
                        "approval_date": seller.approval_date.isoformat()
                    }
                })
            except Exception as e:
                admin_logger.error(f"Failed to create KYC approval notification: {e}")
                
        elif action.action == "reject_kyc":
            seller.kyc_status = "rejected"
            seller.approval_date = None
            message = "Seller KYC rejected"
            
            # Create notification for KYC rejection
            try:
                create_notification(db, {
                    "user_id": str(seller.id),
                    "type": "account_verified",
                    "title": "KYC Verification Required",
                    "message": f"Your KYC verification was not approved. Please review your documents and resubmit for verification.",
                    "priority": "high",
                    "channels": ["in_app", "email"],
                    "data": {
                        "seller_id": str(seller.id),
                        "kyc_status": "rejected",
                        "action_required": True
                    }
                })
            except Exception as e:
                admin_logger.error(f"Failed to create KYC rejection notification: {e}")
        else:
            raise HTTPException(status_code=400, detail="Invalid action")
        
        db.commit()
        
        admin_logger.info(f"Admin {user['id']} {action.action} for seller {seller_id}")
        
        return AdminResponse(
            success=True,
            message=message,
            data={"seller_id": str(seller_id), "new_status": seller.kyc_status}
        )
        
    except HTTPException:
        raise
    except Exception as e:
        log_error(admin_logger, f"Failed to update seller KYC status", e)
        raise HTTPException(status_code=500, detail="Failed to update KYC status")


@router.get("/products", response_model=AdminListResponse)
async def get_admin_products(
    user=Depends(role_required(["admin"])),
    db: Session = Depends(get_db),
    seller_id: Optional[UUID] = Query(None),
    category_id: Optional[UUID] = Query(None),
    status: Optional[str] = Query(None),
    search: Optional[str] = Query(None),
    low_stock: Optional[bool] = Query(None),
    page: int = Query(1, ge=1),
    limit: int = Query(20, ge=1, le=100)
):
    """Get products list for admin management"""
    try:
        offset = (page - 1) * limit
        
        # Build query
        query = (
            db.query(Product)
            .join(SellerProfile, Product.seller_id == SellerProfile.id)
            .join(Category, Product.category_id == Category.id)
            .options(
                joinedload(Product.seller),
                joinedload(Product.category)
            )
        )
        
        # Apply filters
        if seller_id:
            query = query.filter(Product.seller_id == seller_id)
        
        if category_id:
            query = query.filter(Product.category_id == category_id)
        
        if status:
            query = query.filter(Product.status == status)
        
        if search:
            query = query.filter(Product.name.ilike(f"%{search}%"))
        
        if low_stock:
            query = query.filter(Product.stock_quantity < 10)
        
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
        
        # Format response
        product_list = []
        for product in products:
            product_data = AdminProductListResponse(
                id=product.id,
                name=product.name,
                description=product.description,
                price=product.price,
                stock_quantity=product.stock_quantity,
                status=product.status,
                created_at=product.created_at,
                updated_at=product.updated_at,
                seller_id=product.seller_id,
                seller_name=product.seller.business_name,
                category_id=product.category_id,
                category_name=product.category.name,
                images_count=len(product.images)
            )
            product_list.append(product_data.dict())
        
        return AdminListResponse(
            success=True,
            message="Products retrieved successfully",
            data=product_list,
            pagination={
                "page": page,
                "limit": limit,
                "total_pages": (total_products + limit - 1) // limit,
                "has_next": page * limit < total_products,
                "has_prev": page > 1
            },
            total=total_products
        )
        
    except Exception as e:
        log_error(admin_logger, f"Failed to fetch products list", e)
        raise HTTPException(status_code=500, detail="Failed to fetch products")


@router.get("/orders", response_model=AdminListResponse)
async def get_admin_orders(
    user=Depends(role_required(["admin"])),
    db: Session = Depends(get_db),
    status: Optional[str] = Query(None),
    buyer_id: Optional[UUID] = Query(None),
    page: int = Query(1, ge=1),
    limit: int = Query(20, ge=1, le=100)
):
    """Get orders list for admin management"""
    try:
        offset = (page - 1) * limit
        
        # Build query
        query = (
            db.query(Order)
            .join(Profile, Order.buyer_id == Profile.id)
            .join(User, Profile.id == User.id)
            .options(
                joinedload(Order.buyer).joinedload(Profile.user),
                joinedload(Order.order_items)
            )
        )
        
        # Apply filters
        if status:
            query = query.filter(Order.status == status)
        
        if buyer_id:
            query = query.filter(Order.buyer_id == buyer_id)
        
        # Get total count
        total_orders = query.count()
        
        # Get paginated results
        orders = (
            query
            .order_by(desc(Order.created_at))
            .offset(offset)
            .limit(limit)
            .all()
        )
        
        # Format response
        order_list = []
        for order in orders:
            order_data = AdminOrderListResponse(
                id=order.id,
                buyer_id=order.buyer_id,
                buyer_name=order.buyer.name if order.buyer else "Unknown",
                buyer_email=order.buyer.user.email if order.buyer and order.buyer.user else "Unknown",
                total_amount=order.total_amount,
                status=order.status,
                delivery_address=order.delivery_address,
                created_at=order.created_at,
                updated_at=order.updated_at,
                items_count=len(order.order_items)
            )
            order_list.append(order_data.dict())
        
        return AdminListResponse(
            success=True,
            message="Orders retrieved successfully",
            data=order_list,
            pagination={
                "page": page,
                "limit": limit,
                "total_pages": (total_orders + limit - 1) // limit,
                "has_next": page * limit < total_orders,
                "has_prev": page > 1
            },
            total=total_orders
        )
        
    except Exception as e:
        log_error(admin_logger, f"Failed to fetch orders for admin", e)
        raise HTTPException(status_code=500, detail="Failed to fetch orders")


@router.get("/orders/{order_id}", response_model=AdminResponse)
async def get_admin_order_details(
    order_id: UUID,
    user=Depends(role_required(["admin"])),
    db: Session = Depends(get_db)
):
    """Get detailed information about a specific order for admin"""
    try:
        # Get order with all related data (excluding payments - we'll query them separately)
        order = (
            db.query(Order)
            .join(Profile, Order.buyer_id == Profile.id)
            .join(User, Profile.id == User.id)
            .options(
                joinedload(Order.buyer).joinedload(Profile.user),
                joinedload(Order.order_items).joinedload(OrderItem.product).joinedload(Product.images),
                joinedload(Order.order_items).joinedload(OrderItem.product).joinedload(Product.seller),
                joinedload(Order.order_items).joinedload(OrderItem.product).joinedload(Product.category),
                joinedload(Order.delivery_addr),
                # Removed joinedload(Order.payments) - we'll query payments separately
            )
            .filter(Order.id == order_id)
            .first()
        )
        
        if not order:
            raise HTTPException(status_code=404, detail="Order not found")
        
        # Query payments separately to ensure we get only payments for this order
        order_payments = (
            db.query(Payment)
            .filter(Payment.order_id == order.id)
            .all()
        )
        
        # Format order data
        order_data = {
            "id": str(order.id),
            "buyer_id": str(order.buyer_id),
            "buyer_name": order.buyer.name if order.buyer else "Unknown",
            "buyer_email": order.buyer.user.email if order.buyer and order.buyer.user else "Unknown",
            "total_amount": float(order.total_amount),
            "status": order.status,
            "delivery_address": order.delivery_address,
            "created_at": order.created_at.isoformat(),
            "updated_at": order.updated_at.isoformat(),
            "order_items": [
                {
                    "id": str(item.id),
                    "product": {
                        "id": str(item.product.id),
                        "name": item.product.name,
                        "description": item.product.description,
                        "price": float(item.product.price),
                        "images": [
                            {
                                "id": str(img.id),
                                "image_url": img.image_url
                            } for img in item.product.images
                        ],
                        "seller": {
                            "id": str(item.product.seller.id),
                            "business_name": item.product.seller.business_name,
                            "contact_email": item.product.seller.contact_email
                        } if item.product.seller else None,
                        "category": {
                            "id": str(item.product.category.id),
                            "name": item.product.category.name
                        } if item.product.category else None
                    },
                    "quantity": item.quantity,
                    "price": float(item.price),
                    "status": item.status
                } for item in order.order_items
            ],
            "payments": [
                {
                    "id": str(payment.id),
                    "amount": float(payment.amount),
                    "status": payment.status,
                    "payment_method": payment.payment_method,
                    "transaction_id": payment.transaction_id,
                    "created_at": payment.created_at.isoformat()
                } for payment in order_payments
            ]
        }
        
        return AdminResponse(
            success=True,
            message="Order details retrieved successfully",
            data=order_data
        )
        
    except HTTPException:
        raise
    except Exception as e:
        log_error(admin_logger, f"Failed to fetch order details for {order_id}", e)
        raise HTTPException(status_code=500, detail="Failed to fetch order details")


@router.patch("/orders/{order_id}/mark-paid", response_model=AdminResponse)
async def mark_order_as_paid(
    order_id: UUID,
    user=Depends(role_required(["admin"])),
    db: Session = Depends(get_db)
):
    """Mark an order as paid (admin only)"""
    try:        
        order_service = OrderService()
        
        # Update order status to paid
        result = order_service.update_order_status(
            db=db,
            order_id=order_id,
            new_status="paid",
            user_id=user["id"],
            user_role="admin",
            notes="Order marked as paid by admin"
        )
        
        admin_logger.info(f"Order {order_id} marked as paid by admin {user['id']}")
        
        return AdminResponse(
            success=True,
            message="Order marked as paid successfully",
            data=result
        )
        
    except HTTPException:
        raise
    except Exception as e:
        log_error(admin_logger, f"Failed to mark order {order_id} as paid", e)
        raise HTTPException(status_code=500, detail="Failed to mark order as paid")


@router.patch("/orders/bulk/mark-paid", response_model=AdminResponse)
async def bulk_mark_orders_as_paid(
    order_ids: List[UUID],
    user=Depends(role_required(["admin"])),
    db: Session = Depends(get_db)
):
    """Bulk mark multiple orders as paid (admin only)"""
    try:        
        order_service = OrderService()
        results = []
        successful_count = 0
        failed_count = 0
        
        for order_id in order_ids:
            try:
                result = order_service.update_order_status(
                    db=db,
                    order_id=order_id,
                    new_status="paid",
                    user_id=user["id"],
                    user_role="admin",
                    notes="Order marked as paid by admin (bulk action)"
                )
                results.append({"order_id": str(order_id), "success": True, "data": result})
                successful_count += 1
            except Exception as e:
                results.append({"order_id": str(order_id), "success": False, "error": str(e)})
                failed_count += 1
        
        admin_logger.info(f"Bulk mark as paid: {successful_count} successful, {failed_count} failed by admin {user['id']}")
        
        return AdminResponse(
            success=failed_count == 0,
            message=f"Bulk mark as paid completed: {successful_count} successful, {failed_count} failed",
            data={
                "total_processed": len(order_ids),
                "successful_count": successful_count,
                "failed_count": failed_count,
                "results": results
            }
        )
        
    except Exception as e:
        log_error(admin_logger, f"Failed to bulk mark orders as paid", e)
        raise HTTPException(status_code=500, detail="Failed to bulk mark orders as paid")


@router.get("/products", response_model=AdminListResponse)
async def get_admin_products(
    current_admin=Depends(role_required(["admin"])),
    db: Session = Depends(get_db),
    page: int = Query(1, ge=1, description="Page number"),
    limit: int = Query(20, ge=1, le=100, description="Items per page"),
    filters: AdminProductListFilters = Depends()
):
    """Get all platform products for admin oversight"""
    try:
        admin_logger.info(f"Admin fetching products - page: {page}, limit: {limit}")
        
        # Build base query with relationships
        query = (
            db.query(Product)
            .options(
                joinedload(Product.seller),
                joinedload(Product.category),
                joinedload(Product.images)
            )
        )
        
        # Apply filters
        if filters.seller_id:
            query = query.filter(Product.seller_id == filters.seller_id)
        
        if filters.category_id:
            query = query.filter(Product.category_id == filters.category_id)
        
        if filters.status:
            query = query.filter(Product.status == filters.status)
        
        if filters.min_price is not None:
            query = query.filter(Product.price >= filters.min_price)
        
        if filters.max_price is not None:
            query = query.filter(Product.price <= filters.max_price)
        
        if filters.search:
            search_term = f"%{filters.search}%"
            query = query.filter(
                or_(
                    Product.name.ilike(search_term),
                    Product.description.ilike(search_term)
                )
            )
        
        if filters.created_after:
            query = query.filter(Product.created_at >= filters.created_after)
        
        if filters.created_before:
            query = query.filter(Product.created_at <= filters.created_before)
        
        # Get total count
        total_products = query.count()
        
        # Apply pagination and ordering
        products = (
            query
            .order_by(desc(Product.created_at))
            .offset((page - 1) * limit)
            .limit(limit)
            .all()
        )
        
        # Format response
        product_list = []
        for product in products:
            product_data = AdminProductListResponse(
                id=product.id,
                name=product.name,
                description=product.description,
                price=product.price,
                stock_quantity=product.stock_quantity,
                status=product.status,
                seller_id=product.seller_id,
                seller_name=product.seller.business_name if product.seller else "Unknown",
                category_id=product.category_id,
                category_name=product.category.name if product.category else "Uncategorized",
                images_count=len(product.images) if product.images else 0,
                created_at=product.created_at,
                updated_at=product.updated_at
            )
            product_list.append(product_data.dict())
        
        return AdminListResponse(
            success=True,
            message="Products retrieved successfully",
            data=product_list,
            pagination={
                "page": page,
                "limit": limit,
                "total_pages": (total_products + limit - 1) // limit,
                "has_next": page * limit < total_products,
                "has_prev": page > 1,
                "total": total_products
            }
        )
        
    except Exception as e:
        log_error(admin_logger, f"Failed to fetch products for admin", e)
        raise HTTPException(status_code=500, detail="Failed to fetch products")


@router.patch("/products/{product_id}/status", response_model=AdminResponse)
async def update_product_status(
    product_id: UUID,
    request: AdminProductActionRequest,
    current_admin=Depends(role_required(["admin"])),
    db: Session = Depends(get_db)
):
    """Update product status (admin moderation)"""
    try:
        admin_logger.info(f"Admin updating product {product_id} status to {request.action}")
        
        # Get product
        product = db.query(Product).filter(Product.id == product_id).first()
        if not product:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Product not found"
            )
        
        # Update product status based on action
        if request.action == "approve":
            product.status = "active"
        elif request.action == "reject":
            product.status = "inactive"
        elif request.action == "disable":
            product.status = "inactive"
        else:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Invalid action. Must be 'approve', 'reject', or 'disable'"
            )
        
        product.updated_at = func.current_timestamp()
        db.commit()
        
        admin_logger.info(f"Product {product_id} status updated to {product.status} by admin")
        
        return AdminResponse(
            success=True,
            message=f"Product {request.action}d successfully",
            data={
                "product_id": str(product_id),
                "new_status": product.status,
                "action": request.action,
                "notes": request.notes
            }
        )
        
    except HTTPException:
        raise
    except Exception as e:
        log_error(admin_logger, f"Failed to update product {product_id} status", e)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to update product status"
        )


@router.patch("/users/{user_id}/action", response_model=AdminResponse)
async def update_user_action(
    user_id: UUID,
    action: AdminUserActionRequest,
    user=Depends(role_required(["admin"])),
    db: Session = Depends(get_db)
):
    """Update user action (lock, unlock, verify email, reset login attempts)"""
    try:
        # Get the target user
        target_user = db.query(User).filter(User.id == user_id).first()
        if not target_user:
            raise HTTPException(status_code=404, detail="User not found")
        
        # Prevent admin from locking themselves
        if str(target_user.id) == user["id"]:
            raise HTTPException(status_code=400, detail="Cannot perform action on yourself")
        
        if action.action == "lock_account":
            # Lock user account
            if action.lock_duration_hours:
                lock_until = datetime.utcnow() + timedelta(hours=action.lock_duration_hours)
            else:
                lock_until = datetime.utcnow() + timedelta(hours=24)  # Default 24 hours
            
            target_user.locked_until = lock_until
            message = f"User account locked for {action.lock_duration_hours or 24} hours"
            
        elif action.action == "unlock_account":
            # Unlock user account
            target_user.locked_until = None
            message = "User account unlocked"
            
        elif action.action == "verify_email":
            # Verify user email
            target_user.email_verified = True
            target_user.email_verified_at = datetime.utcnow()
            message = "User email verified"
            
        elif action.action == "reset_login_attempts":
            # Reset failed login attempts
            target_user.failed_login_attempts = 0
            message = "Login attempts reset"
            
        else:
            raise HTTPException(status_code=400, detail="Invalid action")
        
        # Update user
        target_user.updated_at = func.current_timestamp()
        db.commit()
        
        # Log the action
        admin_logger.info(f"Admin {user['id']} performed {action.action} on user {user_id}. Reason: {action.reason}")
        
        return AdminResponse(
            success=True,
            message=message,
            data={
                "user_id": str(user_id),
                "action": action.action,
                "reason": action.reason,
                "performed_by": user["id"]
            }
        )
        
    except HTTPException:
        raise
    except Exception as e:
        log_error(admin_logger, f"Failed to perform user action {action.action}", e)
        raise HTTPException(status_code=500, detail="Failed to perform user action")


# ---------------- ADMIN PAYOUT MANAGEMENT ----------------

@router.get("/payouts", response_model=AdminPayoutListResponse)
async def get_pending_payouts(
    page: int = Query(1, ge=1, description="Page number"),
    limit: int = Query(20, ge=1, le=100, description="Items per page"),
    user=Depends(role_required(["admin"])),
    db: Session = Depends(get_db)
):
    """Get all pending payouts for admin processing"""
    try:
        # Get all payouts with pagination and seller details
        offset = (page - 1) * limit
        payouts_query = db.query(SellerPayout).options(joinedload(SellerPayout.seller)).order_by(desc(SellerPayout.created_at))
        total_count = payouts_query.count()
        payouts = payouts_query.offset(offset).limit(limit).all()
        
        payout_responses = [
            {
                "id": str(payout.id),
                "seller_id": str(payout.seller_id),
                "amount": float(payout.amount),
                "platform_fee": float(payout.platform_fee),
                "net_amount": float(payout.net_amount),
                "status": payout.status,
                "transfer_reference": payout.transfer_reference,
                "account_number": payout.account_number,
                "bank_code": payout.bank_code,
                "bank_name": payout.bank_name,
                "created_at": payout.created_at.isoformat(),
                "processed_at": payout.processed_at.isoformat() if payout.processed_at else None,
                "failure_reason": payout.failure_reason,
                "seller": {
                    "business_name": payout.seller.business_name,
                    "contact_email": payout.seller.contact_email,
                    "contact_phone": payout.seller.contact_phone,
                    "website_url": payout.seller.website_url,
                    "kyc_status": payout.seller.kyc_status
                } if payout.seller else None
            }
            for payout in payouts
        ]
        
        total_pages = (total_count + limit - 1) // limit
        
        return AdminPayoutListResponse(
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
        log_error(admin_logger, f"Failed to get pending payouts", e)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to retrieve pending payouts"
        )

@router.post("/payouts/process", response_model=PayoutProcessResponse)
async def process_payout(
    request: PayoutProcessRequest,
    user=Depends(role_required(["admin"])),
    db: Session = Depends(get_db)
):
    """Process a pending payout"""
    try:
        success = seller_payout_service.process_payout(db=db, payout_id=request.payout_id)
        
        if success:
            return PayoutProcessResponse(
                success=True,
                message="Payout processing initiated successfully",
                data=None
            )
        else:
            return PayoutProcessResponse(
                success=False,
                message="Failed to process payout",
                data=None
            )
        
    except Exception as e:
        log_error(admin_logger, f"Failed to process payout {request.payout_id}", e)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to process payout"
        )

@router.post("/payouts/cancel", response_model=PayoutProcessResponse)
async def cancel_payout(
    request: PayoutProcessRequest,
    user=Depends(role_required(["admin"])),
    db: Session = Depends(get_db)
):
    """Cancel a pending payout"""
    try:
        payout = db.query(SellerPayout).filter(SellerPayout.id == request.payout_id).first()
        if not payout:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Payout not found"
            )
        
        if payout.status != "pending":
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Only pending payouts can be cancelled"
            )
        
        payout.status = "cancelled"
        payout.failure_reason = "Cancelled by admin"
        db.commit()
        
        return PayoutProcessResponse(
            success=True,
            message="Payout cancelled successfully",
            data=None
        )
        
    except HTTPException:
        raise
    except Exception as e:
        log_error(admin_logger, f"Failed to cancel payout {request.payout_id}", e)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to cancel payout"
        )

@router.get("/payouts/stats", response_model=dict)
async def get_payout_stats(
    user=Depends(role_required(["admin"])),
    db: Session = Depends(get_db)
):
    """Get payout statistics for admin dashboard"""
    try:
        total_payouts = db.query(SellerPayout).count()
        pending_payouts = db.query(SellerPayout).filter(SellerPayout.status == "pending").count()
        processing_payouts = db.query(SellerPayout).filter(SellerPayout.status == "processing").count()
        completed_payouts = db.query(SellerPayout).filter(SellerPayout.status == "completed").count()
        failed_payouts = db.query(SellerPayout).filter(SellerPayout.status == "failed").count()
        
        # Calculate total amounts
        total_amount = db.query(func.sum(SellerPayout.amount)).scalar() or 0
        pending_amount = db.query(func.sum(SellerPayout.amount)).filter(SellerPayout.status == "pending").scalar() or 0
        completed_amount = db.query(func.sum(SellerPayout.amount)).filter(SellerPayout.status == "completed").scalar() or 0
        
        return {
            "success": True,
            "data": {
                "total_payouts": total_payouts,
                "pending_payouts": pending_payouts,
                "processing_payouts": processing_payouts,
                "completed_payouts": completed_payouts,
                "failed_payouts": failed_payouts,
                "total_amount": float(total_amount),
                "pending_amount": float(pending_amount),
                "completed_amount": float(completed_amount)
            }
        }
        
    except Exception as e:
        log_error(admin_logger, "Failed to get payout stats", e)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to retrieve payout statistics"
        )

# ---------------- ASSET MANAGEMENT ----------------

@router.get("/inspections", response_model=AdminListResponse)
async def get_admin_inspections(
    user=Depends(role_required(["admin"])),
    db: Session = Depends(get_db),
    status: Optional[str] = Query(None),
    asset_type: Optional[str] = Query(None),
    page: int = Query(1, ge=1),
    limit: int = Query(20, ge=1, le=100)
):
    """Get all inspections for admin management"""
    try:
        offset = (page - 1) * limit
        query = db.query(GeneralInspection).options(
            joinedload(GeneralInspection.user).joinedload(User.profile),
            joinedload(GeneralInspection.seller),
            joinedload(GeneralInspection.property),
            joinedload(GeneralInspection.car)
        )
        
        if status:
            query = query.filter(GeneralInspection.status == status)
        if asset_type:
            query = query.filter(GeneralInspection.asset_type == asset_type)
            
        total = query.count()
        inspections = query.order_by(desc(GeneralInspection.created_at)).offset(offset).limit(limit).all()
        
        # Simple formatting for now
        data = []
        for insp in inspections:
            data.append({
                "id": str(insp.id),
                "asset_type": insp.asset_type,
                "asset_id": str(insp.asset_id),
                "inspection_date": insp.inspection_date.isoformat() if insp.inspection_date else None,
                "status": insp.status,
                "created_at": insp.created_at.isoformat(),
                "user_email": insp.user.email,
                "seller_business_name": insp.seller.business_name if insp.seller else "N/A",
                "asset_title": (insp.property.title if insp.asset_type == 'property' and insp.property else 
                              (f"{insp.car.brand} {insp.car.model}" if insp.asset_type == 'automotive' and insp.car else "Asset"))
            })
            
        return AdminListResponse(
            success=True,
            message="Inspections retrieved successfully",
            data=data,
            pagination={
                "page": page,
                "limit": limit,
                "total_pages": (total + limit - 1) // limit,
                "has_next": page * limit < total,
                "has_prev": page > 1
            },
            total=total
        )
    except Exception as e:
        log_error(admin_logger, "Failed to fetch inspections", e)
        raise HTTPException(status_code=500, detail="Failed to fetch inspections")

@router.get("/agreements", response_model=AdminListResponse)
async def get_admin_agreements(
    user=Depends(role_required(["admin"])),
    db: Session = Depends(get_db),
    status: Optional[str] = Query(None),
    asset_type: Optional[str] = Query(None),
    page: int = Query(1, ge=1),
    limit: int = Query(20, ge=1, le=100)
):
    """Get all agreements for admin management"""
    try:
        offset = (page - 1) * limit
        query = db.query(GeneralAgreement).options(
            joinedload(GeneralAgreement.user).joinedload(User.profile),
            joinedload(GeneralAgreement.seller),
            joinedload(GeneralAgreement.property),
            joinedload(GeneralAgreement.car)
        )
        
        if status:
            query = query.filter(GeneralAgreement.status == status)
        if asset_type:
            query = query.filter(GeneralAgreement.asset_type == asset_type)
            
        total = query.count()
        agreements = query.order_by(desc(GeneralAgreement.created_at)).offset(offset).limit(limit).all()
        
        data = []
        for ag in agreements:
            data.append({
                "id": str(ag.id),
                "asset_type": ag.asset_type,
                "asset_id": str(ag.asset_id),
                "total_price": float(ag.total_price),
                "deposit_paid": float(ag.deposit_paid or 0),
                "total_paid": float((ag.total_price or 0) - (ag.remaining_balance or 0)),
                "remaining_balance": float(ag.remaining_balance or 0),
                "status": ag.status,
                "created_at": ag.created_at.isoformat(),
                "user_email": ag.user.email,
                "seller_business_name": ag.seller.business_name if ag.seller else "N/A",
                "asset_title": (ag.property.title if ag.asset_type == 'property' and ag.property else 
                              (f"{ag.car.brand} {ag.car.model}" if ag.asset_type == 'automotive' and ag.car else "Asset"))
            })
            
        return AdminListResponse(
            success=True,
            message="Agreements retrieved successfully",
            data=data,
            pagination={
                "page": page,
                "limit": limit,
                "total_pages": (total + limit - 1) // limit,
                "has_next": page * limit < total,
                "has_prev": page > 1,
                "total": total
            },
            total=total
        )
    except Exception as e:
        log_error(admin_logger, "Failed to fetch agreements", e)
        raise HTTPException(status_code=500, detail="Failed to fetch agreements")

@router.get("/inspections/{id}")
async def get_admin_inspection(
    id: UUID,
    db: Session = Depends(get_db),
    user=Depends(role_required(["admin"]))
):
    try:
        inspection = db.query(GeneralInspection).filter(GeneralInspection.id == id).first()
        if not inspection:
            raise HTTPException(status_code=404, detail="Inspection not found")
        
        # Simple data mapping
        return {
            "success": True,
            "data": {
                "id": str(inspection.id),
                "seller_id": str(inspection.seller_id),
                "user_id": str(inspection.user_id),
                "asset_type": inspection.asset_type,
                "asset_id": str(inspection.asset_id),
                "unit_id": str(inspection.unit_id) if inspection.unit_id else None,
                "inspection_date": inspection.inspection_date.isoformat() if inspection.inspection_date else None,
                "notes": inspection.notes,
                "agreed_price": float(inspection.agreed_price) if inspection.agreed_price else 0,
                "status": inspection.status,
                "created_at": inspection.created_at.isoformat(),
                "user": {"name": inspection.user.profile.name if inspection.user.profile else "N/A", "email": inspection.user.email},
                "seller": {"business_name": inspection.seller.business_name if inspection.seller else "N/A"},
                "asset": {
                    "title": inspection.property.title if inspection.asset_type == 'property' and inspection.property else (inspection.car.brand + " " + inspection.car.model if inspection.asset_type == 'automotive' and inspection.car else "Asset"),
                    "price": float(inspection.property.price if inspection.asset_type == 'property' and inspection.property else (inspection.car.price if inspection.asset_type == 'automotive' and inspection.car else 0)),
                    "image_url": inspection.property.images[0].image_url if inspection.asset_type == 'property' and hasattr(inspection.property, 'images') and inspection.property.images else inspection.car.images[0].image_url if inspection.asset_type == 'automotive' and hasattr(inspection.car, 'images') and inspection.car.images else None
                },
                "acquisition_session": {
                    "id": str(inspection.acquisition_session.id),
                    "proposed_price": float(inspection.acquisition_session.proposed_price) if inspection.acquisition_session.proposed_price else 0,
                    "title": inspection.acquisition_session.title
                } if inspection.acquisition_session else None
            }
        }
    except HTTPException: raise
    except Exception as e:
        log_error(admin_logger, f"Failed to fetch inspection {id}", e)
        raise HTTPException(status_code=500, detail="Internal server error")

@router.put("/inspections/{id}/status")
async def update_admin_inspection_status(
    id: UUID,
    payload: dict,
    db: Session = Depends(get_db),
    user=Depends(role_required(["admin"]))
):
    try:
        inspection = db.query(GeneralInspection).filter(GeneralInspection.id == id).first()
        if not inspection:
            raise HTTPException(status_code=404, detail="Inspection not found")
        
        new_status = payload.get("status")
        notes = payload.get("notes")
        agreed_price = payload.get("agreed_price")
        unit_id = payload.get("unit_id")
        
        if agreed_price is not None:
            inspection.agreed_price = agreed_price
            if inspection.acquisition_session_id:
                sess = db.query(RealEstateSessionRequest).filter(RealEstateSessionRequest.id == inspection.acquisition_session_id).first()
                if sess: sess.proposed_price = agreed_price
        
        if unit_id:
            inspection.unit_id = unit_id

        if notes:
            inspection.notes = notes

        if new_status: 
            inspection.status = new_status
            
            # Sync session status
            if inspection.acquisition_session_id:
                sess = db.query(RealEstateSessionRequest).filter(RealEstateSessionRequest.id == inspection.acquisition_session_id).first()
                if sess:
                    if new_status == "confirmed": sess.status = "inspecting"
                    elif new_status == "agreement_pending": sess.status = "processing"
                    elif new_status == "cancelled": sess.status = "declined"
            
            # Update specific unit status if applicable using unified logic
            asset_service.update_unit_status(
                db, 
                inspection.asset_type, 
                new_status, 
                unit_id=inspection.unit_id, 
                asset_id=inspection.asset_id
            )
        
        db.commit()
        return {"success": True, "message": "Inspection status and session updated"}
    except Exception as e:
        db.rollback()
        log_error(admin_logger, f"Failed to update inspection {id}", e)
        raise HTTPException(status_code=500, detail="Internal server error")

@router.get("/agreements/{id}")
async def get_admin_agreement(
    id: UUID,
    db: Session = Depends(get_db),
    user=Depends(role_required(["admin"]))
):
    try:
        agreement = db.query(GeneralAgreement).filter(GeneralAgreement.id == id).first()
        if not agreement:
            raise HTTPException(status_code=404, detail="Agreement not found")
        
        return {
            "success": True,
            "data": {
                "id": str(agreement.id),
                "seller_id": str(agreement.seller_id),
                "user_id": str(agreement.user_id),
                "asset_type": agreement.asset_type,
                "asset_id": str(agreement.asset_id),
                "total_price": float(agreement.total_price),
                "deposit_paid": float(agreement.deposit_paid or 0),
                "total_paid": float((agreement.total_price or 0) - (agreement.remaining_balance or 0)),
                "remaining_balance": float(agreement.remaining_balance or 0),
                "plan_type": agreement.plan_type,
                "status": agreement.status,
                "created_at": agreement.created_at.isoformat(),
                "user": {"email": agreement.user.email, "name": agreement.user.name or "N/A"},
                "seller": {"business_name": agreement.seller.business_name if agreement.seller else "N/A"},
                "asset": {
                    "title": agreement.property.title if agreement.asset_type == 'property' and agreement.property else (agreement.car.brand + " " + agreement.car.model if agreement.asset_type == 'automotive' and agreement.car else "Asset"),
                    "price": float(agreement.total_price)
                }
            }
        }
    except HTTPException: raise
    except Exception as e:
        log_error(admin_logger, f"Failed to fetch agreement {id}", e)
        raise HTTPException(status_code=500, detail="Internal server error")

@router.put("/agreements/{id}/status")
async def update_admin_agreement_status(
    id: UUID,
    payload: dict,
    db: Session = Depends(get_db),
    user=Depends(role_required(["admin"]))
):
    try:
        agreement = db.query(GeneralAgreement).filter(GeneralAgreement.id == id).first()
        if not agreement:
            raise HTTPException(status_code=404, detail="Agreement not found")
        
        status_val = payload.get("status")
        if status_val: 
            agreement.status = status_val
            # Sync session status
            if agreement.acquisition_session_id:
                sess = db.query(RealEstateSessionRequest).filter(RealEstateSessionRequest.id == agreement.acquisition_session_id).first()
                if sess:
                    if status_val == "completed": sess.status = "acquired"
                    elif status_val == "active": sess.status = "processing"
                    elif status_val == "cancelled": sess.status = "declined"
            
            # Update property unit statuses
            if agreement.asset_type == "property":
                # Sync parent property status too
                prop = db.query(Property).filter(Property.id == agreement.asset_id).first()
                if prop:
                    if status_val == "completed":
                        if agreement.acquisition_session_id: prop.status = "acquired"
                        else: prop.status = "rented" if prop.listing_type == "rental" else "sold"
                    elif status_val == "active":
                        prop.status = "under_financing"
                    elif status_val == "cancelled":
                        prop.status = "available"

                if agreement.acquisition_session_id:
                    # Entire property acquisition
                    unit_status = "acquired" if status_val == "completed" else "under_financing" if status_val == "active" else "available"
                    db.query(PropertyUnit).filter(PropertyUnit.property_id == agreement.asset_id).update({"status": unit_status})
                elif agreement.unit_id:
                    # Individual unit transaction
                    unit = db.query(PropertyUnit).filter(PropertyUnit.id == agreement.unit_id).first()
                    if unit:
                        if status_val == "completed":
                            # Determine if rented or sold
                            unit.status = "rented" if prop and prop.listing_type == "rental" else "sold"
                        elif status_val == "active":
                            unit.status = "under_financing"
                        elif status_val == "cancelled":
                            unit.status = "available"
        
        db.commit()
        return {"success": True, "message": "Agreement status updated"}
    except Exception as e:
        db.rollback()
        log_error(admin_logger, f"Failed to update agreement {id}", e)
        raise HTTPException(status_code=500, detail="Internal server error")


# ---------------- REAL ESTATE MANAGEMENT ----------------

@router.get("/real-estate/properties", response_model=AdminListResponse)
async def list_admin_properties(
    db: Session = Depends(get_db),
    user=Depends(role_required(["admin"])),
    page: int = Query(1, ge=1),
    limit: int = Query(12, ge=1, le=100),
    status: Optional[str] = Query(None),
    search: Optional[str] = Query(None)
):
    """List all listed properties from all sellers with search and pagination"""
    try:
        query = db.query(Property).options(
            joinedload(Property.seller),
            joinedload(Property.images)
        )
        
        if status:
            query = query.filter(Property.status == status)
            
        if search:
            search_pattern = f"%{search}%"
            # We join SellerProfile to enable search by business_name
            query = query.join(SellerProfile, Property.seller_id == SellerProfile.id).filter(
                or_(
                    Property.title.ilike(search_pattern),
                    Property.location.ilike(search_pattern),
                    Property.description.ilike(search_pattern),
                    SellerProfile.business_name.ilike(search_pattern)
                )
            )
            
        total = query.count()
        offset = (page - 1) * limit
        paginated = query.order_by(desc(Property.created_at)).offset(offset).limit(limit).all()
        
        return AdminListResponse(
            success=True,
            message="All property listings fetched successfully",
            data=[PropertyResponse.model_validate(p) for p in paginated],
            pagination={
                "page": page,
                "limit": limit,
                "total": total,
                "total_pages": (total + limit - 1) // limit,
                "has_next": page * limit < total,
                "has_prev": page > 1
            },
            total=total
        )
    except Exception as e:
        log_error(admin_logger, "Failed to fetch all property listings", e)
        raise HTTPException(status_code=500, detail="Failed to fetch property listings")

# ---------------- REAL ESTATE ACQUISITION ----------------

@router.get("/real-estate/sessions", response_model=AdminListResponse)
async def list_admin_real_estate_sessions(
    db: Session = Depends(get_db),
    page: int = Query(1, ge=1),
    limit: int = Query(10, ge=1, le=100),
    user=Depends(role_required(["admin"]))
):
    """List all real estate acquisition session requests"""
    try:
        
        requests = property_service.list_session_requests(db)
        total = len(requests)
        
        # Simple pagination
        start = (page - 1) * limit
        end = start + limit
        paginated_requests = requests[start:end]
        
        return AdminListResponse(
            success=True,
            message="Real estate sessions fetched successfully",
            data=[SessionRequestResponse.model_validate(r) for r in paginated_requests],
            pagination={
                "total": total,
                "page": page,
                "limit": limit,
                "total_pages": (total + limit - 1) // limit
            },
            total=total
        )
    except Exception as e:
        log_error(admin_logger, "Failed to fetch real estate sessions", e)
        raise HTTPException(status_code=500, detail="Failed to fetch real estate sessions")


@router.patch("/real-estate/sessions/{id}", response_model=AdminResponse)
async def update_real_estate_session_status(
    id: UUID,
    payload: dict,
    db: Session = Depends(get_db),
    user=Depends(role_required(["admin"]))
):
    """Update status of a real estate session request"""
    try:
        status_val = payload.get("status")
        notes = payload.get("notes")
        
        updated_request = property_service.update_session_status(db, id, status_val, notes)
        
        return AdminResponse(
            success=True,
            message=f"Session status updated to {status_val}",
            data={
                "id": str(updated_request.id),
                "status": updated_request.status
            }
        )
    except HTTPException:
        raise
    except Exception as e:
        log_error(admin_logger, f"Failed to update session {id}", e)
        raise HTTPException(status_code=500, detail="Failed to update session stats")

@router.post("/real-estate/sessions/{id}/accept", response_model=AdminResponse)
async def accept_real_estate_session(
    id: UUID,
    payload: dict,
    db: Session = Depends(get_db),
    user=Depends(role_required(["admin"]))
):
    """Accept a real estate session request and schedule inspection"""
    try:
        inspection_date_str = payload.get("inspection_date")
        notes = payload.get("notes")
        
        if not inspection_date_str:
            raise HTTPException(status_code=400, detail="inspection_date is required")
            
        inspection_date = datetime.fromisoformat(inspection_date_str.replace("Z", "+00:00"))
        
        updated_request = property_service.accept_session_request(
            db=db, 
            request_id=id, 
            admin_id=UUID(user["id"]), 
            inspection_date=inspection_date, 
            notes=notes
        )
        
        return AdminResponse(
            success=True,
            message=f"Session request accepted and inspection scheduled",
            data={
                "id": str(updated_request.id),
                "status": updated_request.status
            }
        )
    except HTTPException:
        raise
    except Exception as e:
        log_error(admin_logger, f"Failed to accept session {id}", e)
        raise HTTPException(status_code=500, detail="Failed to accept session request")
        raise HTTPException(status_code=500, detail="Failed to update session status")


@router.get("/real-estate/inventory", response_model=AdminListResponse)
async def list_admin_internal_inventory(
    db: Session = Depends(get_db),
    page: int = Query(1, ge=1),
    limit: int = Query(12, ge=1, le=100),
    user=Depends(role_required(["admin"]))
):
    """List properties acquired by the platform (internal inventory)"""
    try:
        inventory = property_service.list_internal_inventory(db)
        total = len(inventory)
        
        start = (page - 1) * limit
        end = start + limit
        paginated_inventory = inventory[start:end]
        
        return AdminListResponse(
            success=True,
            message="Internal inventory fetched successfully",
            data=[PropertyResponse.model_validate(p) for p in paginated_inventory],
            pagination={
                "total": total,
                "page": page,
                "limit": limit,
                "total_pages": (total + limit - 1) // limit
            },
            total=total
        )
    except Exception as e:
        log_error(admin_logger, "Failed to fetch internal inventory", e)
        raise HTTPException(status_code=500, detail="Failed to fetch internal inventory")
        
@router.post("/real-estate/properties/{id}/publish", response_model=AdminResponse)
async def publish_acquired_property(
    id: UUID,
    payload: PropertyPublish,
    user=Depends(role_required(["admin"])),
    db: Session = Depends(get_db)
):
    """Publish an acquired property with a new price"""
    try:
        prop = db.query(Property).filter(Property.id == id).first()
        if not prop:
            raise HTTPException(status_code=404, detail="Property not found")
            
        if prop.status != "acquired":
            raise HTTPException(status_code=400, detail=f"Only properties in 'acquired' status can be published. Current status: {prop.status}")
            
        # Update price and status
        prop.price = payload.new_price
        prop.status = "available"
        
        # Also update all units status to 'available'
        if prop.units:
            for unit in prop.units:
                unit.status = "available"
        
        # Optionally update session request status to 'acquired' or 'published'
        if prop.acquisition_session_id:
            session_req = db.query(RealEstateSessionRequest).filter(RealEstateSessionRequest.id == prop.acquisition_session_id).first()
            if session_req:
                session_req.status = "acquired" # Resetting to acquired just in case, or maybe specific state?
        
        db.commit()
        
        return AdminResponse(
            success=True,
            message=f"Property '{prop.title}' successfully published with new price ₦{payload.new_price:,.2f}"
        )
    except HTTPException:
        raise
    except Exception as e:
        log_error(admin_logger, f"Failed to publish property {id}", e)
        raise HTTPException(status_code=500, detail="Failed to publish property")
