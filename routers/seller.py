from fastapi import APIRouter, Depends, HTTPException, status, Query
from sqlalchemy.orm import Session, joinedload
from sqlalchemy import func, desc
from typing import Optional, List
from uuid import UUID

from db.session import get_db
from core.auth import role_required, get_current_user
from core.model import User, SellerProfile, Product, Order, OrderItem, ProductImage, Category
from schemas.products import ProductResponse, ProductCreate, ProductUpdate
from schemas.order import OrderResponse
from schemas.seller import (
    SellerProfileResponse, 
    SellerProfileUpdate, 
    SellerStatsResponse,
    SellerProductsResponse,
    SellerOrdersResponse,
    SellerAnalyticsResponse
)
from core.logging_config import get_logger, log_error

# Get logger for seller routes
seller_logger = get_logger("routers.seller")

router = APIRouter()


@router.get("/profile", response_model=SellerProfileResponse)
async def get_seller_profile(
    user=Depends(role_required(["seller", "admin"])),
    db: Session = Depends(get_db)
):
    """Get seller profile information"""
    try:
        seller_profile = (
            db.query(SellerProfile)
            .options(joinedload(SellerProfile.user))
            .filter(SellerProfile.id == user["id"])
            .first()
        )
        
        if not seller_profile:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Seller profile not found"
            )
        
        return SellerProfileResponse(
            success=True,
            message="Seller profile retrieved successfully",
            data=seller_profile
        )
    except HTTPException:
        raise
    except Exception as e:
        log_error(seller_logger, f"Failed to fetch seller profile for user {user['id']}", e)
        raise HTTPException(status_code=500, detail="Failed to fetch seller profile")


@router.put("/profile", response_model=SellerProfileResponse)
async def update_seller_profile(
    profile_data: SellerProfileUpdate,
    user=Depends(role_required(["seller", "admin"])),
    db: Session = Depends(get_db)
):
    """Update seller profile information"""
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
        
        # Update profile fields
        update_data = profile_data.model_dump(exclude_unset=True)
        for field, value in update_data.items():
            setattr(seller_profile, field, value)
        
        db.commit()
        db.refresh(seller_profile)
        
        return SellerProfileResponse(
            success=True,
            message="Seller profile updated successfully",
            data=seller_profile
        )
    except HTTPException:
        raise
    except Exception as e:
        log_error(seller_logger, f"Failed to update seller profile for user {user['id']}", e)
        raise HTTPException(status_code=500, detail="Failed to update seller profile")


@router.get("/stats", response_model=SellerStatsResponse)
async def get_seller_stats(
    user=Depends(role_required(["seller", "admin"])),
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
                "business_name": seller_profile.business_name
            }
        )
    except HTTPException:
        raise
    except Exception as e:
        log_error(seller_logger, f"Failed to fetch seller stats for user {user['id']}", e)
        raise HTTPException(status_code=500, detail="Failed to fetch seller statistics")


@router.get("/products", response_model=SellerProductsResponse)
async def get_seller_products(
    user=Depends(role_required(["seller", "admin"])),
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
        
        # Build query
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
    user=Depends(role_required(["seller", "admin"])),
    db: Session = Depends(get_db),
    page: int = Query(1, ge=1, description="Page number"),
    limit: int = Query(10, ge=1, le=100, description="Items per page"),
    status: Optional[str] = Query(None, description="Filter by order status")
):
    """Get orders for seller's products"""
    try:
        seller_id = user["id"]
        offset = (page - 1) * limit
        
        # Build query for orders containing seller's products
        query = (
            db.query(Order)
            .join(OrderItem)
            .join(Product)
            .options(
                joinedload(Order.buyer),
                joinedload(Order.delivery_addr),
                joinedload(Order.order_items).joinedload(OrderItem.product)
            )
            .filter(Product.seller_id == seller_id)
            .distinct()
        )
        
        # Apply status filter
        if status:
            query = query.filter(Order.status == status)
        
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


@router.get("/analytics", response_model=SellerAnalyticsResponse)
async def get_seller_analytics(
    user=Depends(role_required(["seller", "admin"])),
    db: Session = Depends(get_db),
    period: str = Query("30d", description="Analytics period: 7d, 30d, 90d, 1y")
):
    """Get seller analytics data"""
    try:
        seller_id = user["id"]
        
        # Calculate date range based on period
        from datetime import datetime, timedelta
        now = datetime.utcnow()
        
        if period == "7d":
            start_date = now - timedelta(days=7)
        elif period == "30d":
            start_date = now - timedelta(days=30)
        elif period == "90d":
            start_date = now - timedelta(days=90)
        elif period == "1y":
            start_date = now - timedelta(days=365)
        else:
            start_date = now - timedelta(days=30)
        
        # Revenue analytics
        revenue_data = (
            db.query(
                func.date(Order.created_at).label('date'),
                func.sum(OrderItem.quantity * OrderItem.price).label('revenue')
            )
            .join(OrderItem)
            .join(Product)
            .filter(
                Product.seller_id == seller_id,
                Order.created_at >= start_date,
                Order.status == "delivered"
            )
            .group_by(func.date(Order.created_at))
            .order_by('date')
            .all()
        )
        
        # Order count analytics
        order_data = (
            db.query(
                func.date(Order.created_at).label('date'),
                func.count(Order.id).label('orders')
            )
            .join(OrderItem)
            .join(Product)
            .filter(
                Product.seller_id == seller_id,
                Order.created_at >= start_date
            )
            .group_by(func.date(Order.created_at))
            .order_by('date')
            .all()
        )
        
        # Top selling products
        top_products = (
            db.query(
                Product.name,
                func.sum(OrderItem.quantity).label('total_sold'),
                func.sum(OrderItem.quantity * OrderItem.price).label('revenue')
            )
            .join(OrderItem)
            .join(Order)
            .filter(
                Product.seller_id == seller_id,
                Order.created_at >= start_date,
                Order.status == "delivered"
            )
            .group_by(Product.id, Product.name)
            .order_by(desc('total_sold'))
            .limit(10)
            .all()
        )
        
        return SellerAnalyticsResponse(
            success=True,
            message="Seller analytics retrieved successfully",
            data={
                "revenue_data": [{"date": str(r.date), "revenue": float(r.revenue or 0)} for r in revenue_data],
                "order_data": [{"date": str(o.date), "orders": o.orders} for o in order_data],
                "top_products": [
                    {
                        "name": p.name,
                        "total_sold": int(p.total_sold or 0),
                        "revenue": float(p.revenue or 0)
                    } for p in top_products
                ],
                "period": period
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
