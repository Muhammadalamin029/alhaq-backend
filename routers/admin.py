from fastapi import APIRouter, Depends, HTTPException, status, Query
from sqlalchemy.orm import Session, joinedload
from sqlalchemy import func, desc, and_, or_
from typing import Optional, List
from uuid import UUID
from datetime import datetime, timedelta

from db.session import get_db
from core.auth import role_required
from core.model import User, Profile, SellerProfile, Product, Order, OrderItem, Category
from schemas.admin import (
    AdminDashboardStats, AdminUserListResponse, AdminUserDetailResponse,
    AdminSellerListResponse, AdminProductListResponse, AdminOrderListResponse,
    AdminUserActionRequest, AdminSellerActionRequest, AdminProductActionRequest,
    AdminResponse, AdminListResponse, AdminUserListFilters,
    AdminSellerListFilters, AdminProductListFilters, AdminOrderListFilters
)
from core.logging_config import get_logger, log_error
from core.auth_service import auth_service
from pydantic import BaseModel, Field

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
        
        # Revenue calculation
        total_revenue = (
            db.query(func.sum(OrderItem.quantity * OrderItem.price))
            .join(Order)
            .filter(Order.status == "delivered")
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
                Order.status == "delivered"
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
        
        stats = AdminDashboardStats(
            total_users=total_users,
            total_products=total_products,
            total_orders=total_orders,
            total_payments=total_orders,  # Simplified
            total_revenue=float(total_revenue),
            new_users_today=new_users_today,
            new_orders_today=new_orders_today,
            revenue_today=float(revenue_today),
            pending_seller_approvals=pending_seller_approvals,
            locked_users=locked_users,
            out_of_stock_products=out_of_stock_products,
            pending_orders=pending_orders
        )
        
        return AdminResponse(
            success=True,
            message="Admin dashboard stats retrieved successfully",
            data=stats.dict()
        )
        
    except Exception as e:
        log_error(admin_logger, f"Failed to fetch admin dashboard stats", e)
        raise HTTPException(status_code=500, detail="Failed to fetch dashboard stats")


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
                description=seller.description,
                contact_email=seller.contact_email,
                contact_phone=seller.contact_phone,
                website_url=seller.website_url,
                kyc_status=seller.kyc_status,
                approval_date=seller.approval_date,
                total_products=seller.total_products,
                total_orders=seller.total_orders,
                total_revenue=seller.total_revenue,
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
        elif action.action == "reject_kyc":
            seller.kyc_status = "rejected"
            seller.approval_date = None
            message = "Seller KYC rejected"
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
            .join(User, Profile.user_id == User.id)
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
        
    except HTTPException:
        raise
    except Exception as e:
        log_error(admin_logger, f"Failed to perform user action", e)
        raise HTTPException(status_code=500, detail="Failed to perform user action")


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
