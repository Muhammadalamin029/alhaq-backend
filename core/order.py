from core.model import Order, OrderItem, Product
from sqlalchemy.orm import Session, joinedload
from sqlalchemy import UUID
from typing import List, Optional, Tuple, Dict
from schemas.order import OrderItemCreate
from core.inventory import inventory_service
from fastapi import HTTPException, status
from decimal import Decimal
import logging
from contextlib import contextmanager

logger = logging.getLogger(__name__)


class OrderService:
    @contextmanager
    def transaction_context(self, db: Session):
        """Context manager for database transactions with proper rollback"""
        try:
            yield db
            db.commit()
        except Exception as e:
            db.rollback()
            logger.error(f"Order transaction failed: {str(e)}")
            raise

    def _with_relationships(self, query):
        """Helper to always eager-load related entities for an order"""
        return query.options(
            joinedload(Order.buyer),
            joinedload(Order.order_items).joinedload(OrderItem.product),
            joinedload(Order.delivery_addr),
            joinedload(Order.payments),
        )

    def _validate_and_reserve_stock(self, db: Session, product_id: UUID, requested_quantity: int, order_id: UUID = None) -> Dict:
        """Validate stock availability and reserve it atomically"""
        try:
            # Check availability first
            availability = inventory_service.check_product_availability(
                db, product_id, requested_quantity)

            if not availability['is_available']:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=f"Insufficient stock for product {product_id}. "
                    f"Available: {availability['available_stock']}, "
                    f"Requested: {requested_quantity}"
                )

            return availability

        except HTTPException:
            raise
        except Exception as e:
            logger.error(
                f"Stock validation failed for product {product_id}: {str(e)}")
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Failed to validate product availability"
            )

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
        try:
            with self.transaction_context(db):
                # Validate and get product info
                availability = self._validate_and_reserve_stock(
                    db, item.product_id, item.quantity
                )

                # Calculate total
                total_amount = Decimal(
                    str(item.quantity)) * Decimal(str(price))

                # Create order
                new_order = Order(
                    buyer_id=buyer_id,
                    total_amount=float(total_amount),
                )
                db.add(new_order)
                db.flush()  # ensures new_order.id is available

                # Reserve stock for the order
                inventory_service.reserve_stock(
                    db, item.product_id, item.quantity, new_order.id
                )

                # Create order items
                order_item = OrderItem(
                    order_id=new_order.id,
                    product_id=item.product_id,
                    quantity=item.quantity,
                    price=price,
                )
                db.add(order_item)

                # Don't commit here - context manager handles it
                db.refresh(new_order)
                return new_order

        except Exception as e:
            logger.error(
                f"Failed to create order for buyer {buyer_id}: {str(e)}")
            raise

    def create_order_item(
        self, db: Session, order_id: UUID, product_id: UUID, quantity: int, price: float
    ):
        try:
            with self.transaction_context(db):
                # Validate and reserve stock
                availability = self._validate_and_reserve_stock(
                    db, product_id, quantity, order_id
                )

                # Reserve stock
                inventory_service.reserve_stock(
                    db, product_id, quantity, order_id)

                # Create order item
                new_item = OrderItem(
                    order_id=order_id,
                    product_id=product_id,
                    quantity=quantity,
                    price=price,
                )
                db.add(new_item)
                db.refresh(new_item)
                return new_item

        except Exception as e:
            logger.error(
                f"Failed to create order item for order {order_id}: {str(e)}")
            raise

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

    def update_order_item_quantity(
        self, db: Session, order_id: UUID, item_id: UUID, quantity: int
    ):
        try:
            with self.transaction_context(db):
                # Fetch order item with product + order
                order_item = (
                    db.query(OrderItem)
                    .options(joinedload(OrderItem.product), joinedload(OrderItem.order))
                    .filter(OrderItem.id == item_id, OrderItem.order_id == order_id)
                    .first()
                )
                if not order_item:
                    return None

                old_quantity = order_item.quantity
                quantity_diff = quantity - old_quantity

                if quantity_diff > 0:
                    inventory_service.reserve_stock(
                        db, order_item.product_id, quantity_diff, order_id
                    )
                elif quantity_diff < 0:
                    inventory_service.release_stock(
                        db, order_item.product_id, abs(quantity_diff), order_id
                    )

                # Update quantity
                order_item.quantity = quantity

                # Recalculate order total using loaded relationship
                order = order_item.order
                new_total = sum(
                    Decimal(str(item.price)) * item.quantity for item in order.order_items
                )
                order.total_amount = float(new_total)

                db.flush()  # ensures pending changes are visible
                db.refresh(order)  # refresh with latest DB state
                return order

        except Exception as e:
            logger.error(f"Failed to update order item quantity: {str(e)}")
            raise

      # ---------------- DELETE ----------------

    def delete_order(self, db: Session, order_id: UUID):
        try:
            with self.transaction_context(db):
                # Get order with items loaded
                order = (
                    db.query(Order)
                    .options(joinedload(Order.order_items))
                    .filter(Order.id == order_id)
                    .first()
                )
                if not order:
                    return False

                # Release stock for all order items
                stock_items = [
                    {'product_id': item.product_id, 'quantity': item.quantity}
                    for item in order.order_items
                ]

                if stock_items:
                    inventory_service.release_multiple_products(
                        db, stock_items, order_id)

                # Delete the order (cascade will handle order items)
                db.delete(order)
                return True

        except Exception as e:
            logger.error(f"Failed to delete order {order_id}: {str(e)}")
            raise

    def delete_order_item(self, db: Session, order_id: UUID, item_id: UUID):
        try:
            with self.transaction_context(db):
                # Get order item with product loaded
                order_item = (
                    db.query(OrderItem)
                    .options(joinedload(OrderItem.product))
                    .filter(OrderItem.id == item_id, OrderItem.order_id == order_id)
                    .first()
                )
                if not order_item:
                    return None

                # Release stock for this item
                inventory_service.release_stock(
                    db, order_item.product_id, order_item.quantity, order_id
                )

                # Store item data before deletion
                item_quantity = order_item.quantity
                item_price = order_item.price

                # Delete the order item
                db.delete(order_item)
                db.flush()  # ensure it's removed before recalculation

                # Get order with remaining items
                order = (
                    db.query(Order)
                    .options(joinedload(Order.order_items))
                    .filter(Order.id == order_id)
                    .first()
                )
                if not order:
                    return None

                # Check if any items remain
                if not order.order_items:
                    # Delete the order if no items remain
                    db.delete(order)
                    return "ORDER_DELETED"

                # Otherwise recalc total with proper decimal handling
                new_total = sum(
                    Decimal(str(item.price)) * item.quantity
                    for item in order.order_items
                )
                order.total_amount = float(new_total)

                db.refresh(order)
                return order

        except Exception as e:
            logger.error(f"Failed to delete order item {item_id}: {str(e)}")
            raise

    # ---------------- ORDER STATUS MANAGEMENT ----------------

    def get_valid_status_transitions(self, current_status: str) -> List[str]:
        """Get valid status transitions based on current status"""
        transitions = {
            "pending": ["processing", "cancelled"],
            "processing": ["shipped", "cancelled"],
            "shipped": ["delivered"],
            "delivered": [],  # Final state
            "cancelled": []  # Final state
        }
        return transitions.get(current_status, [])

    def validate_status_transition(self, current_status: str, new_status: str) -> bool:
        """Validate if status transition is allowed"""
        valid_transitions = self.get_valid_status_transitions(current_status)
        return new_status in valid_transitions

    def update_order_status(
        self,
        db: Session,
        order_id: UUID,
        new_status: str,
        user_id: str = None,
        user_role: str = None,
        notes: str = None
    ) -> Dict:
        """Update order status with proper validation and workflow"""
        try:
            with self.transaction_context(db):
                # Get order with relationships
                order = self.get_order_by_id(db, order_id)
                if not order:
                    raise HTTPException(
                        status_code=status.HTTP_404_NOT_FOUND,
                        detail="Order not found"
                    )

                current_status = order.status

                # Check if status transition is valid
                if not self.validate_status_transition(current_status, new_status):
                    valid_transitions = self.get_valid_status_transitions(
                        current_status)
                    raise HTTPException(
                        status_code=status.HTTP_400_BAD_REQUEST,
                        detail=f"Invalid status transition from {current_status} to {new_status}. "
                        f"Valid transitions: {valid_transitions}"
                    )

                # Authorization check
                if user_role == "seller":
                    # Sellers can only update orders containing their products
                    seller_has_items = any(
                        item.product.seller_id == UUID(user_id)
                        for item in order.order_items
                    )
                    if not seller_has_items:
                        raise HTTPException(
                            status_code=status.HTTP_403_FORBIDDEN,
                            detail="You can only update orders containing your products"
                        )

                    # Sellers can only mark orders as shipped or delivered
                    if new_status not in ["shipped", "delivered"]:
                        raise HTTPException(
                            status_code=status.HTTP_403_FORBIDDEN,
                            detail="Sellers can only mark orders as shipped or delivered"
                        )

                elif user_role == "customer":
                    # Customers can only cancel pending orders
                    if new_status != "cancelled" or current_status != "pending":
                        raise HTTPException(
                            status_code=status.HTTP_403_FORBIDDEN,
                            detail="Customers can only cancel pending orders"
                        )

                    # Verify customer owns the order
                    if order.buyer_id != UUID(user_id):
                        raise HTTPException(
                            status_code=status.HTTP_403_FORBIDDEN,
                            detail="You can only update your own orders"
                        )

                # Handle status-specific logic
                old_status = order.status

                if new_status == "cancelled" and old_status in ["pending", "processing"]:
                    # Release stock when order is cancelled
                    stock_items = [
                        {'product_id': item.product_id, 'quantity': item.quantity}
                        for item in order.order_items
                    ]
                    if stock_items:
                        inventory_service.release_multiple_products(
                            db, stock_items, order_id)

                # Update order status
                order.status = new_status

                db.refresh(order)

                logger.info(
                    f"Order {order_id} status updated from {old_status} to {new_status} by user {user_id}")

                return {
                    "order_id": str(order_id),
                    "old_status": old_status,
                    "new_status": new_status,
                    "updated_at": order.updated_at.isoformat() if order.updated_at else None,
                    "notes": notes
                }

        except HTTPException:
            raise
        except Exception as e:
            logger.error(f"Failed to update order status: {str(e)}")
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Failed to update order status"
            )

    def bulk_update_order_status(
        self,
        db: Session,
        order_ids: List[UUID],
        new_status: str,
        user_id: str = None,
        user_role: str = None,
        notes: str = None
    ) -> Dict:
        """Update status for multiple orders"""
        results = {
            "successful_updates": [],
            "failed_updates": [],
            "total_processed": len(order_ids)
        }

        for order_id in order_ids:
            try:
                result = self.update_order_status(
                    db, order_id, new_status, user_id, user_role, notes
                )
                results["successful_updates"].append({
                    "order_id": str(order_id),
                    "result": result
                })
            except Exception as e:
                results["failed_updates"].append({
                    "order_id": str(order_id),
                    "error": str(e)
                })

        return results

    def get_order_status_history(self, db: Session, order_id: UUID) -> Dict:
        """Get order status change history (if implemented with audit table)"""
        # This would require an order_status_history table
        # For now, return current status info
        order = self.get_order_by_id(db, order_id)
        if not order:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Order not found"
            )

        return {
            "order_id": str(order_id),
            "current_status": order.status,
            "created_at": order.created_at.isoformat(),
            "updated_at": order.updated_at.isoformat() if order.updated_at else None,
            "valid_transitions": self.get_valid_status_transitions(order.status)
        }


order_service = OrderService()
