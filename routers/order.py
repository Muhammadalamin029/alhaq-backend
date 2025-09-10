from fastapi import APIRouter, Depends, status, HTTPException, Query
from sqlalchemy.orm import Session
from db.session import get_db
from core.auth import role_required
from core.order import order_service
from core.products import product_service
from schemas.order import OrderResponse, OrderItemCreate, OrderCreate
from decimal import Decimal
from uuid import UUID

router = APIRouter()


@router.get("/", status_code=status.HTTP_200_OK)
async def list_orders(
    user=Depends(role_required(["customer", "admin", "seller"])),
    db: Session = Depends(get_db),
    page: int = Query(1, ge=1, description="Page number"),
    limit: int = Query(10, ge=1, le=100, description="Items per page"),
):
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
    existing_order = order_service.get_orders_by_status(
        db=db, user_id=user["id"], status="pending"
    )
    product = product_service.get_product_by_id(db, payload.product_id)
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
    order_id: str,
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
    quantity: int = Query(..., ge=1),
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
