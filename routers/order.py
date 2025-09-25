from fastapi import APIRouter, Depends, status, HTTPException, Query
from sqlalchemy.orm import Session
from db.session import get_db
from core.auth import role_required
from core.order import order_service
from core.products import product_service
from schemas.order import (
    OrderResponse, OrderItemCreate, OrderCreate,
    OrderStatusUpdate, OrderStatusResponse, BulkOrderStatusUpdate
)
from decimal import Decimal
from uuid import UUID,  uuid4
from core.logging_config import get_logger, log_error

# Get logger for orders routes
orders_logger = get_logger("routers.orders")

router = APIRouter()


@router.get("/", status_code=status.HTTP_200_OK)
async def list_orders(
    user=Depends(role_required(["customer", "admin", "seller"])),
    db: Session = Depends(get_db),
    page: int = Query(1, ge=1, description="Page number"),
    limit: int = Query(10, ge=1, le=100, description="Items per page"),
):
    try:
        orders_logger.info(f"Fetching orders for {user['role']} user {user['id']} - page: {page}, limit: {limit}")
        
        if user["role"] == "admin":
            orders, count = order_service.fetch_orders(db, limit=limit, page=page)
        elif user["role"] == "seller":
            orders, count = order_service.get_orders_by_seller(
                db, seller_id=user["id"], limit=limit, page=page
            )
        else:  # customer
            orders, count = order_service.get_orders_by_buyer(
                db, buyer_id=user["id"], limit=limit, page=page
            )
        
        orders_logger.info(f"Orders fetched successfully for user {user['id']} - count: {count}")
        
        return {
            "success": True,
            "message": "Orders fetched successfully",
            "data": [OrderResponse.model_validate(o) for o in orders],
            "pagination": {
                "page": page,
                "limit": limit,
                "total": count,
                "total_pages": (count + limit - 1) // limit,
            },
        }
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
        "data": OrderResponse.model_validate(order),
    }


@router.post("/", status_code=status.HTTP_201_CREATED)
async def create_order_item(
    payload: OrderItemCreate,
    user=Depends(role_required(["customer", "admin"])),
    db: Session = Depends(get_db)
):
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
        order_service.create_order_item(
            db=db,
            order_id=existing_order.id,
            product_id=payload.product_id,
            quantity=payload.quantity,
            price=price,
        )

        new_total_amount = Decimal(existing_order.total_amount) + Decimal(
            price * payload.quantity
        )

        order_service.update_order_amount(
            db, existing_order.id, new_total_amount
        )

        return {
            "success": True,
            "message": "Order updated successfully",
            "data": OrderResponse.model_validate(existing_order),
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
        "data": OrderResponse.model_validate(new_order),
    }


@router.get("/{order_id}", status_code=status.HTTP_200_OK)
async def fetch_order_by_id(
    order_id: UUID,
    user=Depends(role_required(["customer", "admin", "seller"])),
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
            detail="You do not have permission to view this order."
        )
    elif user["role"] == "seller":
        is_seller_order = any(
            item.product.seller_id == user["id"] for item in order.order_items
        )
        if not is_seller_order:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="You do not have permission to view this order."
            )

    return {
        "success": True,
        "message": "Order fetched successfully",
        "data": OrderResponse.model_validate(order),
    }


@router.put("/{order_id}", status_code=status.HTTP_200_OK)
async def update_order(
    order_id: str,
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
        delivery_address=order_data.delivery_address,
        items=[OrderItemCreate.model_dump(i) for i in order_data.items],
    )

    return {
        "success": True,
        "message": "Order updated successfully",
        "data": OrderResponse.model_validate(updated_order),
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
    
    if product.stock_quantity < quantity:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Insufficient stock. Only {product.stock_quantity} items available"
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
        "data": OrderResponse.model_validate(updated_order),
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
        "data": OrderResponse.model_validate(result),
    }


# ---------------- ORDER STATUS MANAGEMENT ----------------

@router.patch("/{order_id}/status", response_model=OrderStatusResponse)
async def update_order_status(
    order_id: str,
    payload: OrderStatusUpdate,
    user=Depends(role_required(["admin", "seller"])),
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


@router.patch("/bulk/status", response_model=OrderStatusResponse)
async def bulk_update_order_status(
    payload: BulkOrderStatusUpdate,
    user=Depends(role_required(["admin", "seller"])),
    db: Session = Depends(get_db)
):
    """Update status for multiple orders (admin and sellers only)"""
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


@router.get("/status-transitions/{order_id}", response_model=OrderStatusResponse)
async def get_order_status_info(
    order_id: str,
    user=Depends(role_required(["admin", "seller", "customer"])),
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
        elif user["role"] == "seller":
            seller_has_items = any(
                item.product.seller_id == user["id"] for item in order.order_items
            )
            if not seller_has_items:
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail="You can only view orders containing your products"
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
