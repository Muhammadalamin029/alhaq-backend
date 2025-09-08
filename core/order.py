from core.model import Order, OrderItem
from sqlalchemy.orm import Session, joinedload
from sqlalchemy import UUID
from typing import List, Optional


class OrderService:
    def _with_relationships(self, query):
        """Helper to always eager-load related entities for an order"""
        return query.options(
            joinedload(Order.buyer),
            joinedload(Order.order_items).joinedload(OrderItem.product),
            joinedload(Order.checkouts),
            joinedload(Order.delivery_addr),
            joinedload(Order.payments),
        )

    # ---------------- FETCH ORDERS ----------------
    def fetch_orders(self, db: Session):
        return self._with_relationships(db.query(Order)).all()

    def get_order_by_id(self, db: Session, order_id: UUID):
        return (
            self._with_relationships(db.query(Order))
            .filter(Order.id == order_id)
            .first()
        )

    def get_orders_by_buyer(self, db: Session, buyer_id: UUID):
        return (
            self._with_relationships(db.query(Order))
            .filter(Order.buyer_id == buyer_id)
            .all()
        )

    # ---------------- CREATE ----------------
    def create_order(
        self,
        db: Session,
        buyer_id: UUID,
        delivery_address: Optional[UUID],
        items: List[dict],  # list of {product_id, quantity, price}
    ):
        # Calculate total
        total_amount = sum(item["quantity"] * item["price"] for item in items)

        # Create order
        new_order = Order(
            buyer_id=buyer_id,
            delivery_address=delivery_address,
            total_amount=total_amount,
        )
        db.add(new_order)
        db.flush()  # ensures new_order.id is available

        # Create order items
        for item in items:
            order_item = OrderItem(
                order_id=new_order.id,
                product_id=item["product_id"],
                quantity=item["quantity"],
                price=item["price"],
            )
            db.add(order_item)

        db.commit()
        db.refresh(new_order)
        return new_order

    # ---------------- UPDATE ----------------
    def update_order_status(self, db: Session, order_id: UUID, new_status: str):
        order = db.query(Order).filter(Order.id == order_id).first()
        if not order:
            return None
        order.status = new_status
        db.commit()
        db.refresh(order)
        return order

    def update_order(
        self, db: Session, order_id: UUID, **kwargs
    ):
        order = db.query(Order).filter(Order.id == order_id).first()
        if not order:
            return None
        for key, value in kwargs.items():
            setattr(order, key, value)
        db.commit()
        db.refresh(order)
        return order

    # ---------------- DELETE ----------------
    def delete_order(self, db: Session, order_id: UUID):
        order = db.query(Order).filter(Order.id == order_id).first()
        if not order:
            return False
        db.delete(order)
        db.commit()
        return True


order_service = OrderService()
