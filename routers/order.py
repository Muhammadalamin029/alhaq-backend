from fastapi import APIRouter, Depends, status, HTTPException, Query
from sqlalchemy.orm import Session
from db.session import get_db
from core.auth import role_required
from core.order import order_service
from core.products import product_service
from schemas.order import (
    OrderResponse, OrderItemCreate, OrderCreate,
    OrderStatusUpdate, OrderStatusResponse, BulkOrderStatusUpdate, OrderStatus,
    EstimatedDeliveryUpdate
)
from decimal import Decimal
from datetime import date
from uuid import UUID,  uuid4
from core.logging_config import get_logger, log_error
from core.system_settings_service import system_settings_service

# Get logger for orders routes
orders_logger = get_logger("routers.orders")

router = APIRouter()


@router.get("/", status_code=status.HTTP_200_OK)
async def list_orders(
    user=Depends(role_required(["customer", "admin"])),
    db: Session = Depends(get_db),
    page: int = Query(1, ge=1, description="Page number"),
    limit: int = Query(10, ge=1, le=100, description="Items per page"),
    status_filter: OrderStatus | None = Query(None, alias="status", description="Filter by order status"),
    statuses: str | None = Query(None, description="Comma-separated list of statuses; overrides status"),
    start_date: date | None = Query(None, description="Filter orders placed on/after this date"),
    end_date: date | None = Query(None, description="Filter orders placed on/before this date"),
):
    try:
        orders_logger.info(f"Fetching orders for {user['role']} user {user['id']} - page: {page}, limit: {limit}, status: {status_filter}")

        status_value = status_filter.value if status_filter else None

        statuses_value = None
        if statuses:
            requested = [s.strip() for s in statuses.split(",") if s.strip()]
            valid_values = {s.value for s in OrderStatus}
            invalid = [s for s in requested if s not in valid_values]
            if invalid:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=f"Invalid status value(s): {', '.join(invalid)}"
                )
            statuses_value = requested

        if user["role"] == "admin":
            orders, count = order_service.fetch_orders(
                db, limit=limit, page=page, status=status_value, statuses=statuses_value,
                start_date=start_date, end_date=end_date,
            )
        else:  # customer
            orders, count = order_service.get_orders_by_buyer(
                db, buyer_id=user["id"], limit=limit, page=page, status=status_value,
                statuses=statuses_value, start_date=start_date, end_date=end_date,
            )
        
        orders_logger.info(f"Orders fetched successfully for user {user['id']} - count: {count}")
        
        return {
            "success": True,
            "message": "Orders fetched successfully",
            "data": [OrderResponse.model_validate(o).model_dump(by_alias=True) for o in orders],
            "pagination": {
                "page": page,
                "limit": limit,
                "total": count,
                "total_pages": (count + limit - 1) // limit,
            },
        }
    except HTTPException:
        raise
    except Exception as e:
        log_error(orders_logger, f"Failed to fetch orders for user {user['id']}", e,
                  user_id=user['id'], user_role=user['role'], page=page, limit=limit)
        raise HTTPException(status_code=500, detail="Failed to fetch orders")


@router.get("/pending", status_code=status.HTTP_200_OK)
async def get_pending_orders(
    db: Session = Depends(get_db),
    user=Depends(role_required(["customer"])),
):
    order = order_service.get_orders_by_status(
        db, user_id=user["id"], status="pending"
    )
    if not order:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No pending orders found"
        )
    return {
        "success": True,
        "message": "Pending orders fetched successfully",
        "data": OrderResponse.model_validate(order).model_dump(by_alias=True),
    }


@router.get("/track", status_code=status.HTTP_200_OK)
async def track_order(
    order_id: UUID = Query(..., description="Order ID from your receipt or confirmation email"),
    email: str = Query(..., description="The billing email used for this order"),
    db: Session = Depends(get_db),
):
    """Public order lookup — no login required. Only confirms the order
    exists and returns its id/status when the email matches the buyer,
    so a guest can be routed to sign in and view the full order."""
    order = order_service.track_order(db, order_id=order_id, email=email)
    if not order:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No order found matching that Order ID and email address"
        )
    return {
        "success": True,
        "message": "Order found",
        "data": {"order_id": str(order.id), "status": order.status},
    }


@router.post("/", status_code=status.HTTP_201_CREATED)
async def create_order_item(
    payload: OrderItemCreate,
    user=Depends(role_required(["customer", "admin"])),
    db: Session = Depends(get_db)
):
    system_settings_service.require_verified_email_for_user(db, user["id"], "create an order")

    # Additional validation for quantity (belt and suspenders approach)
    if payload.quantity <= 0:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Quantity must be greater than 0"
        )
    
    if payload.quantity > 1000:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Quantity cannot exceed 1000 items per order"
        )
    
    existing_order = order_service.get_orders_by_status(
        db=db, user_id=user["id"], status="pending"
    )
    
    # Validate product exists
    product = product_service.get_product_by_id(db, payload.product_id)
    if not product:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Product not found"
        )
    
    # Validate product is active
    if product.status != "active":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Product is not available for purchase"
        )
    
    # Validate stock availability
    if product.stock_quantity < payload.quantity:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Insufficient stock. Only {product.stock_quantity} items available"
        )
    
    price = product.price
    if existing_order:
        updated_order = order_service.create_order_item(
            db=db,
            order_id=existing_order.id,
            product_id=payload.product_id,
            quantity=payload.quantity,
            price=price,
        )

        return {
            "success": True,
            "message": "Order updated successfully",
            "data": OrderResponse.model_validate(updated_order).model_dump(by_alias=True),
        }

    new_order = order_service.create_order(
        db=db,
        buyer_id=user["id"],
        item=payload,
        price=price,
    )

    return {
        "success": True,
        "message": "Order created successfully",
        "data": OrderResponse.model_validate(new_order).model_dump(by_alias=True),
    }


@router.get("/{order_id}", status_code=status.HTTP_200_OK)
async def fetch_order_by_id(
    order_id: UUID,
    user=Depends(role_required(["customer", "admin"])),
    db: Session = Depends(get_db)
):
    order = order_service.get_order_by_id(db, order_id)

    if not order:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Order not found"
        )

    # Check if user has permission to view this order
    if user["role"] == "customer" and str(order.buyer_id) != user["id"]:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You can only view your own orders"
        )

    return {
        "success": True,
        "message": "Order fetched successfully",
        "data": OrderResponse.model_validate(order).model_dump(by_alias=True),
    }


@router.put("/{order_id}", status_code=status.HTTP_200_OK)
async def update_order(
    order_id: UUID,
    order_data: OrderCreate,
    user=Depends(role_required(["customer"])),
    db: Session = Depends(get_db)
):
    order = order_service.get_order_by_id(db, order_id)
    if not order:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Order not found."
        )

    # Authorization check
    if user["role"] == "customer" and order.buyer_id != UUID(str(user["id"])):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You do not have permission to update this order."
        )

    updated_order = order_service.update_order(
        db,
        order.id,
        delivery_address=order_data.delivery_address_id,
    )

    return {
        "success": True,
        "message": "Order updated successfully",
        "data": OrderResponse.model_validate(updated_order).model_dump(by_alias=True),
    }


@router.put("/{order_id}/items/{item_id}", status_code=status.HTTP_200_OK)
async def update_order_item_quantity(
    order_id: str,
    item_id: str,
    quantity: int = Query(..., ge=1, le=1000),
    user=Depends(role_required(["customer"])),
    db: Session = Depends(get_db)
):
    order = order_service.get_order_by_id(db, order_id)
    if not order:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Order not found."
        )

    # Auth: only the buyer can modify
    if user["role"] == "customer" and order.buyer_id != UUID(str(user["id"])):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You do not have permission to update this order."
        )
    
    # Validate order is still pending (only pending orders can be modified)
    if order.status != "pending":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Only pending orders can be modified"
        )
    
    # Find the order item to validate stock
    order_item = None
    for item in order.order_items:
        if str(item.id) == item_id:
            order_item = item
            break
    
    if not order_item:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Order item not found"
        )
    
    # Validate stock availability
    product = product_service.get_product_by_id(db, order_item.product_id)
    if not product:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Product not found"
        )
    
    # stock_quantity already has order_item.quantity reserved out of it.
    # Only the additional quantity beyond what's currently reserved needs new stock.
    extra_needed = quantity - order_item.quantity
    if extra_needed > 0 and product.stock_quantity < extra_needed:
        available_to_buyer = product.stock_quantity + order_item.quantity
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Insufficient stock. Maximum quantity for this item is {available_to_buyer}"
        )

    updated_order = order_service.update_order_item_quantity(
        db=db,
        order_id=order.id,
        item_id=item_id,
        quantity=quantity,
    )

    if not updated_order:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Order item not found."
        )

    return {
        "success": True,
        "message": "Order item updated successfully",
        "data": OrderResponse.model_validate(updated_order).model_dump(by_alias=True),
    }


@router.delete("/{order_id}", status_code=status.HTTP_200_OK)
async def delete_order(
    order_id: str,
    user=Depends(role_required(["customer"])),
    db: Session = Depends(get_db)
):
    order = order_service.get_order_by_id(db, order_id)
    if not order:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Order not found."
        )

    # Authorization check
    if user["role"] == "customer" and order.buyer_id != UUID(str(user["id"])):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You do not have permission to delete this order."
        )
    
    # Validate order can be deleted (only pending orders)
    if order.status != "pending":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Only pending orders can be deleted"
        )

    order_service.delete_order(db, order_id)

    return {
        "success": True,
        "message": "Order deleted successfully",
        "data": None,
    }


@router.delete("/{order_id}/items/{item_id}", status_code=status.HTTP_200_OK)
async def delete_order_item(
    order_id: str,
    item_id: str,
    user=Depends(role_required(["customer"])),
    db: Session = Depends(get_db)
):
    order = order_service.get_order_by_id(db, order_id)
    if not order:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Order not found."
        )

    # Auth: only buyer can delete items
    if user["role"] == "customer" and order.buyer_id != UUID(str(user["id"])):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You do not have permission to modify this order."
        )
    
    # Validate order is still pending
    if order.status != "pending":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Only pending orders can be modified"
        )

    result = order_service.delete_order_item(
        db=db,
        order_id=order.id,
        item_id=item_id,
    )

    if not result:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Order item not found."
        )

    if result == "ORDER_DELETED":
        return {
            "success": True,
            "message": "Order item deleted successfully. Order had no remaining items and was deleted.",
            "data": None,
        }

    return {
        "success": True,
        "message": "Order item deleted successfully",
        "data": OrderResponse.model_validate(result).model_dump(by_alias=True),
    }


# ---------------- ORDER STATUS MANAGEMENT ----------------

@router.patch("/bulk/status", response_model=OrderStatusResponse)
async def bulk_update_order_status(
    payload: BulkOrderStatusUpdate,
    user=Depends(role_required(["admin"])),
    db: Session = Depends(get_db)
):
    """Update status for multiple orders (admin only)"""
    try:
        results = order_service.bulk_update_order_status(
            db=db,
            order_ids=payload.order_ids,
            new_status=payload.status.value,
            user_id=user["id"],
            user_role=user["role"],
            notes=payload.notes
        )

        success_count = len(results["successful_updates"])
        total_count = results["total_processed"]

        return OrderStatusResponse(
            success=success_count == total_count,
            message=f"Updated {success_count}/{total_count} orders to {payload.status.value}",
            data=results
        )

    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to bulk update order status"
        )


@router.patch("/{order_id}/status", response_model=OrderStatusResponse)
async def update_order_status(
    order_id: str,
    payload: OrderStatusUpdate,
    user=Depends(role_required(["admin"])),
    db: Session = Depends(get_db)
):
    """Update order status with proper workflow validation"""
    try:
        result = order_service.update_order_status(
            db=db,
            order_id=order_id,
            new_status=payload.status.value,
            user_id=user["id"],
            user_role=user["role"],
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
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to update order status"
        )


@router.patch("/{order_id}/estimated-delivery", response_model=OrderStatusResponse)
async def update_estimated_delivery(
    order_id: str,
    payload: EstimatedDeliveryUpdate,
    user=Depends(role_required(["admin"])),
    db: Session = Depends(get_db)
):
    """Admin: set or override an order's estimated delivery date"""
    try:
        order = order_service.update_estimated_delivery(
            db=db,
            order_id=order_id,
            estimated_delivery_date=payload.estimated_delivery_date
        )
        return OrderStatusResponse(
            success=True,
            message="Estimated delivery date updated",
            data={
                "order_id": str(order.id),
                "estimated_delivery_date": order.estimated_delivery_date.isoformat(),
            }
        )
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to update estimated delivery date"
        )


@router.get("/status-transitions/{order_id}", response_model=OrderStatusResponse)
async def get_order_status_info(
    order_id: str,
    user=Depends(role_required(["admin", "customer"])),
    db: Session = Depends(get_db)
):
    """Get order status information and valid transitions"""
    try:
        # First verify user has access to this order
        order = order_service.get_order_by_id(db, order_id)
        if not order:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Order not found"
            )

        # Authorization check
        if user["role"] == "customer" and order.buyer_id != UUID(str(user["id"])):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="You can only view your own orders"
            )

        status_info = order_service.get_order_status_history(db, order_id)
        
        return OrderStatusResponse(
            success=True,
            message="Order status information retrieved",
            data=status_info
        )
        
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to get order status information"
        )


@router.post("/{order_id}/cancel", response_model=OrderStatusResponse)
async def cancel_order(
    order_id: str,
    user=Depends(role_required(["customer", "admin"])),
    db: Session = Depends(get_db)
):
    """Cancel an order (customers can cancel their own pending orders)"""
    try:
        result = order_service.update_order_status(
            db=db,
            order_id=order_id,
            new_status="cancelled",
            user_id=user["id"],
            user_role=user["role"],
            notes="Order cancelled by user"
        )
        
        return OrderStatusResponse(
            success=True,
            message="Order cancelled successfully",
            data=result
        )
        
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to cancel order"
        )


@router.get("/{order_id}/timeline")
async def get_order_timeline(
    order_id: str,
    user=Depends(role_required(["customer", "admin"])),
    db: Session = Depends(get_db)
):
    """Get order timeline/history"""
    try:
        # First verify user has access to this order
        order = order_service.get_order_by_id(db, order_id)
        if not order:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Order not found"
            )

        # Authorization check
        if user["role"] == "customer" and order.buyer_id != UUID(str(user["id"])):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="You can only view your own orders"
            )

        # Create timeline based on order status and dates
        timeline = []
        
        # Order placed
        timeline.append({
            "status": "Order Placed",
            "date": order.created_at.isoformat(),
            "completed": True,
            "description": "Your order has been placed successfully"
        })
        
        # Processing
        if order.status in ["processing", "shipped", "delivered"]:
            timeline.append({
                "status": "Processing",
                "date": order.updated_at.isoformat() if order.status != "pending" else None,
                "completed": order.status in ["processing", "shipped", "delivered"],
                "description": "Your order is being prepared"
            })

        # Paid
        if order.status in ["paid", "shipped", "delivered"]:
            timeline.append({
                "status": "Paid",
                "date": order.updated_at.isoformat(),
                "completed": True,
                "description": "Your payment has been confirmed"
            })

        # Shipped
        if order.status in ["shipped", "delivered"]:
            timeline.append({
                "status": "Shipped",
                "date": order.updated_at.isoformat() if order.status in ["shipped", "delivered"] else None,
                "completed": order.status in ["shipped", "delivered"],
                "description": "Your order has been shipped"
            })
        
        # Delivered
        if order.status == "delivered":
            timeline.append({
                "status": "Delivered",
                "date": order.updated_at.isoformat(),
                "completed": True,
                "description": "Your order has been delivered"
            })
        
        # Cancelled
        if order.status == "cancelled":
            timeline.append({
                "status": "Cancelled",
                "date": order.updated_at.isoformat(),
                "completed": True,
                "description": "Your order has been cancelled"
            })
        
        return {
            "success": True,
            "message": "Order timeline retrieved successfully",
            "data": {
                "order_id": order.id,
                "current_status": order.status,
                "timeline": timeline
            }
        }
        
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to get order timeline"
        )
