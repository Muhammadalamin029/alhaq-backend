from fastapi import APIRouter, Depends, status, HTTPException
from sqlalchemy.orm import Session
from db.session import get_db
from core.auth import role_required
from core.order import order_service
from schemas.order import OrderResponse,  OrderItemCreate

router = APIRouter()


@router.get("/", status_code=status.HTTP_200_OK)
def list_orders(user=Depends(role_required(["customer", "admin", "seller"])), db: Session = Depends(get_db)):
    if user.role == "admin":
        orders = order_service.fetch_orders(db)

    elif user.role == "seller":
        # Fetch orders that include products sold by this seller
        orders = order_service.get_orders_by_seller(db, user.id)

    else:  # customer
        orders = order_service.get_orders_by_buyer(db, user.id)

    return {
        "success": True,
        "message": "Orders fetched successfully",
        "data": [OrderResponse.model_config(o) for o in orders]
    }


@router.post("/", status_code=status.HTTP_201_CREATED)
def create_order(order: OrderItemCreate, user=Depends(role_required(["customer"])), db: Session = Depends(get_db)):
    if not order.items or len(order.items) == 0:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Order must contain at least one item."
        )

    order = order_service.get_orders_by_status(
        db=db, user_id=user.id, status="pending")
    if order:
        order_service.create_order_item(
            order_id=order.id, product_id=order.product_id, quantity=order.quantity, price=order.price)
        new_order = order

        return {
            "success": True,
            "message": "Order updated successfully",
            "data": OrderResponse.model_config(new_order)
        }

    new_order = order_service.create_order(
        db=db,
        buyer_id=user.id,
        delivery_address=order.delivery_address,
        items=[OrderItemCreate.model_dump(i) for i in order.items]
    )

    return {
        "success": True,
        "message": "Order created successfully",
        "data": OrderResponse.model_config(new_order)
    }


@router.get("/{order_id}", status_code=status.HTTP_200_OK)
def get_order(order_id: str, user=Depends(role_required(["customer", "admin", "seller"])), db: Session = Depends(get_db)):
    order = order_service.get_order_by_id(db, order_id)
    if not order:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Order not found."
        )

    # Authorization check
    if user.role == "customer" and order.buyer_id != user.id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You do not have permission to view this order."
        )
    elif user.role == "seller":
        # Check if the order contains products sold by this seller
        seller_product_ids = {
            item.product_id for item in order.order_items if item.product.seller_id == user.id}
        if not seller_product_ids:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="You do not have permission to view this order."
            )

    return {
        "success": True,
        "message": "Order fetched successfully",
        "data": OrderResponse.model_config(order)
    }


@router.put("/{order_id}", status_code=status.HTTP_200_OK)
def update_order(order_id: str, order_data: OrderItemCreate, user=Depends(role_required(["customer"])), db: Session = Depends(get_db)):
    order = order_service.get_order_by_id(db, order_id)
    if not order:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Order not found."
        )

    # Authorization check
    if user.role == "customer" and order.buyer_id != user.id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You do not have permission to update this order."
        )

    updated_order = order_service.update_order(
        db, order.id, delivery_address=order_data.delivery_address, items=[OrderItemCreate.model_dump(i) for i in order_data.items])

    return {
        "success": True,
        "message": "Order updated successfully",
        "data": OrderResponse.model_config(updated_order)
    }


@router.delete("/{order_id}", status_code=status.HTTP_200_OK)
def delete_order(order_id: str, user=Depends(role_required(["customer"])), db: Session = Depends(get_db)):
    order = order_service.get_order_by_id(db, order_id)
    if not order:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Order not found."
        )

    # Authorization check
    if user.role == "customer" and order.buyer_id != user.id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You do not have permission to delete this order."
        )

    order_service.delete_order(db, order)

    return {
        "success": True,
        "message": "Order deleted successfully",
        "data": None
    }
