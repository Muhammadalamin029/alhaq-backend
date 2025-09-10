from core.model import Order, OrderItem, Product
from sqlalchemy.orm import Session, joinedload
from sqlalchemy import UUID
from typing import List, Optional, Tuple
from schemas.order import OrderItemCreate


class OrderService:
    def _with_relationships(self, query):
        """Helper to always eager-load related entities for an order"""
        return query.options(
            joinedload(Order.buyer),
            joinedload(Order.order_items).joinedload(OrderItem.product),
            joinedload(Order.delivery_addr),
            joinedload(Order.payments),
        )
    
    def _validate_stock_availability(self, db: Session, product_id: str, requested_quantity: int):
        """Helper to validate if enough stock is available for a product"""
        from core.products import product_service
        product = product_service.get_product_by_id(db, product_id)
        
        if not product:
            raise ValueError("Product not found")
        
        if product.status != "active":
            raise ValueError("Product is not available for purchase")
        
        if product.stock_quantity < requested_quantity:
            raise ValueError(f"Insufficient stock. Only {product.stock_quantity} items available")
        
        return product

    # ---------------- FETCH ORDERS ----------------
    def fetch_orders(self, db: Session, limit: int = 10, page: int = 1) -> Tuple[List[Order], int]:
        query = self._with_relationships(db.query(Order))
        count = query.count()
        offset = (page - 1) * limit
        orders = query.offset(offset).limit(limit).all()
        return orders, count

    def get_order_by_id(self, db: Session, order_id: UUID):
        return (
            self._with_relationships(db.query(Order))
            .filter(Order.id == order_id)
            .first()
        )

    def get_orders_by_buyer(self, db: Session, buyer_id: UUID, limit: int = 10, page: int = 1) -> Tuple[List[Order], int]:
        query = self._with_relationships(
            db.query(Order)).filter(Order.buyer_id == buyer_id)
        count = query.count()
        offset = (page - 1) * limit
        orders = query.offset(offset).limit(limit).all()
        return orders, count

    def get_orders_by_seller(self, db: Session, seller_id: UUID, limit: int = 10, page: int = 1) -> Tuple[List[Order], int]:
        query = (
            db.query(Order)
            .join(Order.order_items)
            .join(OrderItem.product)
            .filter(Product.seller_id == seller_id)
            .options(
                joinedload(Order.buyer),
                joinedload(Order.order_items).joinedload(OrderItem.product),
                joinedload(Order.checkouts),
                joinedload(Order.delivery_addr),
                joinedload(Order.payments),
            )
        )

        count = query.distinct(Order.id).count()
        offset = (page - 1) * limit
        orders = query.offset(offset).limit(limit).all()

        # Keep only items from this seller
        for order in orders:
            order.order_items = [
                item for item in order.order_items if item.product.seller_id == seller_id
            ]
        return orders, count

    def get_orders_by_status(self, db: Session, user_id: str, status: str): return (self._with_relationships(
        db.query(Order)) .filter(Order.status == status) .filter(Order.buyer_id == user_id) .first())

    # ---------------- CREATE ----------------
    def create_order(
        self,
        db: Session,
        buyer_id: UUID,
        item: OrderItemCreate,
        price: float  # single item
    ):
        # Calculate total
        total_amount = item.quantity * price

        # Create order
        new_order = Order(
            buyer_id=buyer_id,
            total_amount=total_amount,
        )
        db.add(new_order)
        db.flush()  # ensures new_order.id is available

        # Create order items
        order_item = OrderItem(
            order_id=new_order.id,
            product_id=item.product_id,
            quantity=item.quantity,
            price=price,
        )
        db.add(order_item)

        db.commit()
        db.refresh(new_order)
        return new_order

    def create_order_item(
        self, db: Session, order_id: UUID, product_id: UUID, quantity: int, price: float
    ):
        new_item = OrderItem(
            order_id=order_id,
            product_id=product_id,
            quantity=quantity,
            price=price,
        )
        db.add(new_item)
        db.commit()
        db.refresh(new_item)
        return new_item

    # ---------------- UPDATE ----------------
    def update_order_status(self, db: Session, order_id: UUID, new_status: str):
        order = db.query(Order).filter(Order.id == order_id).first()
        if not order:
            return None
        order.status = new_status
        db.commit()
        db.refresh(order)
        return order

    def update_order(self, db: Session, order_id: UUID, **kwargs):
        order = db.query(Order).filter(Order.id == order_id).first()
        if not order:
            return None
        for key, value in kwargs.items():
            setattr(order, key, value)
        db.commit()
        db.refresh(order)
        return order
    
    def update_order_amount(self, db: Session, order_id: UUID, new_amount: float):
        """Update the total amount of an order"""
        order = db.query(Order).filter(Order.id == order_id).first()
        if not order:
            return None
        order.total_amount = new_amount
        db.commit()
        db.refresh(order)
        return order

    def update_order_item_quantity(self, db: Session, order_id: UUID, item_id: UUID, quantity: int):
        order_item = (
            db.query(OrderItem)
            .filter(OrderItem.id == item_id, OrderItem.order_id == order_id)
            .first()
        )
        if not order_item:
            return None

        # Update quantity
        order_item.quantity = quantity
        order_item.price = order_item.product.price  # ensure price is fresh

        # Recalculate order total
        order = db.query(Order).filter(Order.id == order_id).first()
        new_total = sum(i.price * i.quantity for i in order.order_items)
        order.total_amount = new_total

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

    def delete_order_item(self, db: Session, order_id: UUID, item_id: UUID):
        order_item = (
            db.query(OrderItem)
            .filter(OrderItem.id == item_id, OrderItem.order_id == order_id)
            .first()
        )
        if not order_item:
            return None

        db.delete(order_item)
        db.flush()  # ensure it's removed before recalculation

        order = db.query(Order).filter(Order.id == order_id).first()
        if not order:
            return None

        # Check if any items remain
        if not order.order_items:
            # Delete the order if no items remain
            db.delete(order)
            db.commit()
            return "ORDER_DELETED"

        # Otherwise recalc total
        new_total = sum(i.price * i.quantity for i in order.order_items)
        order.total_amount = new_total

        db.commit()
        db.refresh(order)
        return order


order_service = OrderService()
