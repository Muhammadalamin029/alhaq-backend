from core.model import Order, OrderItem
from sqlalchemy.orm import Session, joinedload
from sqlalchemy import UUID
from typing import List, Optional, Tuple, Dict
from schemas.order import OrderItemCreate
from core.inventory import inventory_service
from core.tasks import send_order_shipped_email, send_order_delivered_email
from fastapi import HTTPException, status
from decimal import Decimal
import logging
from contextlib import contextmanager

logger = logging.getLogger(__name__)


# Import notification utilities
from core.notification_utils import send_order_notification


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

    def calculate_overall_order_status(self, item_statuses):
        """Reduce a list of item statuses to a single overall order status."""
        if not item_statuses:
            return 'pending'

        status_counts = {}
        for s in item_statuses:
            status_counts[s] = status_counts.get(s, 0) + 1

        total_items = len(item_statuses)

        # All delivered
        if status_counts.get('delivered', 0) == total_items:
            return 'delivered'

        # All cancelled
        if status_counts.get('cancelled', 0) == total_items:
            return 'cancelled'

        # Partial cancellation
        if status_counts.get('cancelled', 0) > 0:
            return 'partially_cancelled'

        # Partial delivery
        if status_counts.get('delivered', 0) > 0:
            return 'partially_delivered'

        # All shipped
        if status_counts.get('shipped', 0) == total_items:
            return 'shipped'

        # Partial shipping
        if status_counts.get('shipped', 0) > 0:
            return 'partially_shipped'

        # All paid
        if status_counts.get('paid', 0) == total_items:
            return 'paid'

        # Any processing
        if status_counts.get('processing', 0) > 0:
            return 'processing'

        return 'pending'

    def _validate_and_reserve_stock(self, db: Session, product_id: UUID, requested_quantity: int) -> Dict:
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
    def fetch_orders(self, db: Session, limit: int = 10, page: int = 1, status: Optional[str] = None) -> Tuple[List[Order], int]:
        query = self._with_relationships(db.query(Order))
        if status:
            query = query.filter(Order.status == status)
        count = query.count()
        offset = (page - 1) * limit
        orders = query.offset(offset).limit(limit).all()
        return orders, count

    def get_order_by_id(self, db: Session, order_id: UUID):
        order = (
            self._with_relationships(db.query(Order))
            .filter(Order.id == order_id)
            .first()
        )
        if order:
            # Format payments (create a new attribute to avoid SQLAlchemy conflicts)
            order.formatted_payments = [
                {
                    "id": str(payment.id),
                    "amount": float(payment.amount),
                    "status": payment.status,
                    "payment_method": payment.payment_method,
                    "transaction_id": payment.transaction_id,
                    "transaction_metadata": payment.transaction_metadata,
                    "created_at": payment.created_at.isoformat()
                } for payment in order.payments
            ] if order.payments else []
        return order

    def get_orders_by_buyer(self, db: Session, buyer_id: UUID, limit: int = 10, page: int = 1, status: Optional[str] = None) -> Tuple[List[Order], int]:
        query = self._with_relationships(
            db.query(Order)).filter(Order.buyer_id == buyer_id)
        if status:
            query = query.filter(Order.status == status)
        count = query.count()
        offset = (page - 1) * limit
        orders = query.offset(offset).limit(limit).all()

        # Format payments for each order
        for order in orders:
            order.formatted_payments = [
                {
                    "id": str(payment.id),
                    "amount": float(payment.amount),
                    "status": payment.status,
                    "payment_method": payment.payment_method,
                    "transaction_id": payment.transaction_id,
                    "transaction_metadata": payment.transaction_metadata,
                    "created_at": payment.created_at.isoformat()
                } for payment in order.payments
            ] if order.payments else []

        return orders, count

    def get_orders_by_status(self, db: Session, user_id: str, status: str):
        """Get order by status for a specific user"""
        return (
            self._with_relationships(db.query(Order))
            .filter(Order.status == status)
            .filter(Order.buyer_id == user_id)
            .first()
        )

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
                self._validate_and_reserve_stock(
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
                    status="pending"  # Initialize item status
                )
                db.add(order_item)
                db.flush()

                # Ensure total is consistent (already set), but recalc in case of float/decimal quirks
                db.refresh(new_order)
                recalc_total = sum(Decimal(str(i.price)) * i.quantity for i in new_order.order_items)
                new_order.total_amount = float(recalc_total)
                db.commit()  # Commit the changes to persist the total_amount update
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
                # Load order with items
                order = (
                    db.query(Order)
                    .options(joinedload(Order.order_items))
                    .filter(Order.id == order_id)
                    .first()
                )
                if not order:
                    raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Order not found")

                # Check if item already exists in order
                existing_item = next((i for i in order.order_items if i.product_id == product_id), None)

                if existing_item:
                    # Validate and reserve additional stock only for the diff
                    self._validate_and_reserve_stock(db, product_id, quantity, order_id)
                    inventory_service.reserve_stock(db, product_id, quantity, order_id)

                    # Increase quantity
                    existing_item.quantity = existing_item.quantity + quantity
                else:
                    # Validate and reserve stock for new item
                    self._validate_and_reserve_stock(db, product_id, quantity, order_id)
                    inventory_service.reserve_stock(db, product_id, quantity, order_id)

                    # Create new order item
                    new_item = OrderItem(
                        order_id=order_id,
                        product_id=product_id,
                        quantity=quantity,
                        price=price,
                        status="pending"  # Initialize item status
                    )
                    db.add(new_item)
                    db.flush()

                # Recalculate order total
                db.refresh(order)
                new_total = sum(Decimal(str(item.price)) * item.quantity for item in order.order_items)
                order.total_amount = float(new_total)
                db.commit()  # Commit the changes to persist the total_amount update
                db.refresh(order)
                return order

        except Exception as e:
            logger.error(
                f"Failed to create order item for order {order_id}: {str(e)}")
            raise

    # ---------------- UPDATE ----------------
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

                db.commit()  # Commit the changes to persist the total_amount update
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

                db.commit()  # Commit the changes to persist the total_amount update
                db.refresh(order)
                return order

        except Exception as e:
            logger.error(f"Failed to delete order item {item_id}: {str(e)}")
            raise

    # ---------------- ORDER STATUS MANAGEMENT ----------------

    def get_valid_status_transitions(self, current_status: str, user_role: str = None) -> List[str]:
        """Get valid status transitions from current status.

        Admin can change any status (including processing -> paid); this is
        also the base ruleset customers are further restricted against in
        update_order_status.
        """
        transitions = {
            "pending": ["processing", "cancelled"],
            "processing": ["paid", "cancelled"],
            "paid": ["shipped", "cancelled"],
            "shipped": ["delivered"],
            "delivered": [],  # Final state
            "cancelled": []  # Final state
        }
        return transitions.get(current_status, [])

    def validate_status_transition(self, current_status: str, new_status: str, user_role: str = None) -> bool:
        """Validate if status transition is allowed"""
        valid_transitions = self.get_valid_status_transitions(current_status, user_role)
        return new_status in valid_transitions

    def calculate_overall_order_status_from_items(self, order_items):
        """Calculate overall order status directly from item statuses.

        Single-vendor model: there's exactly one implicit seller/store, so
        the old two-level reduction (group items by seller, reduce each
        seller's items to a status, then combine across sellers) collapses
        into a single reduction over all item statuses.
        """
        if not order_items:
            return 'pending'
        return self.calculate_overall_order_status([item.status for item in order_items])

    # Linear progression used to prevent admin from regressing items that have already advanced
    _STATUS_RANK: Dict[str, int] = {
        "pending": 0,
        "processing": 1,
        "paid": 2,
        "shipped": 3,
        "delivered": 4,
        "cancelled": 5,
        # Partial states are intermediate; treat like paid rank so shipped/delivered items are kept
        "partially_shipped": 2,
        "partially_delivered": 3,
        "partially_cancelled": 2,
    }

    def update_all_order_items_status(
        self,
        db: Session,
        order_id: UUID,
        new_status: str
    ) -> Dict:
        """Update status for all items in an order to match the order status.

        Items that are already at a more-advanced status are skipped so that
        progress already recorded (e.g., already shipped) is never overwritten
        by a later status push.
        """
        try:
            order_items = db.query(OrderItem).filter(OrderItem.order_id == order_id).all()

            if not order_items:
                logger.warning(f"No order items found for order {order_id}")
                return {"items_updated": 0, "status": new_status}

            target_rank = self._STATUS_RANK.get(new_status, -1)

            items_updated = 0
            for item in order_items:
                current_rank = self._STATUS_RANK.get(item.status, -1)
                if current_rank > target_rank:
                    logger.info(
                        f"Skipping item {item.id}: already at '{item.status}' (rank {current_rank}) "
                        f"> target '{new_status}' (rank {target_rank})"
                    )
                    continue
                old_item_status = item.status
                item.status = new_status
                items_updated += 1
                logger.info(f"Updated item {item.id} status from {old_item_status} to {new_status}")

            db.flush()

            logger.info(f"Updated {items_updated} order items to status {new_status} for order {order_id}")

            return {
                "items_updated": items_updated,
                "status": new_status,
                "order_id": str(order_id)
            }

        except Exception as e:
            logger.error(f"Failed to update all order items status: {str(e)}")
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Failed to update order items status"
            )

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
                order = (
                    self._with_relationships(db.query(Order))
                    .filter(Order.id == order_id)
                    .first()
                )
                if not order:
                    raise HTTPException(
                        status_code=status.HTTP_404_NOT_FOUND,
                        detail="Order not found"
                    )

                current_status = order.status

                # Check if status transition is valid
                if not self.validate_status_transition(current_status, new_status, user_role):
                    valid_transitions = self.get_valid_status_transitions(
                        current_status, user_role)
                    raise HTTPException(
                        status_code=status.HTTP_400_BAD_REQUEST,
                        detail=f"Invalid status transition from {current_status} to {new_status}. "
                        f"Valid transitions: {valid_transitions}"
                    )

                # Authorization check
                if user_role == "customer":
                    # Customers can only cancel pending or processing orders
                    if new_status != "cancelled" or current_status not in ["pending", "processing"]:
                        raise HTTPException(
                            status_code=status.HTTP_403_FORBIDDEN,
                            detail="Customers can only cancel pending or processing orders"
                        )

                    # Verify customer owns the order
                    if str(order.buyer_id) != str(user_id):
                        raise HTTPException(
                            status_code=status.HTTP_403_FORBIDDEN,
                            detail="You can only update your own orders"
                        )

                # Handle status-specific logic
                old_status = order.status

                _pre_delivery = {
                    "pending", "processing", "paid", "shipped",
                    "partially_shipped", "partially_delivered", "partially_cancelled",
                }
                if new_status == "cancelled" and old_status in _pre_delivery:
                    # Release reserved stock for every item that hasn't been delivered
                    stock_items = [
                        {'product_id': item.product_id, 'quantity': item.quantity}
                        for item in order.order_items
                        if item.status not in ("delivered", "cancelled")
                    ]
                    if stock_items:
                        inventory_service.release_multiple_products(
                            db, stock_items, order_id)

                # Update order status
                order.status = new_status
                db.flush()  # Ensure changes are written to DB
                db.refresh(order)

                # Update all order items status to match the order status
                # This ensures consistency between order and item statuses
                self.update_all_order_items_status(db, order_id, new_status)

                logger.info(
                    f"Order {order_id} status updated from {old_status} to {new_status} by user {user_id}")

                # Return success response first
                result = {
                    "order_id": str(order_id),
                    "old_status": old_status,
                    "new_status": new_status,
                    "updated_at": order.updated_at.isoformat() if order.updated_at else None,
                    "notes": notes
                }

                # Send buyer notifications in a separate step (non-blocking)
                try:
                    self._send_order_status_notification(order_id, order, old_status, new_status, user_id, notes)
                except Exception as e:
                    logger.error(f"Failed to send notifications for order {order_id}: {e}")
                    # Don't fail the main operation if notifications fail

                return result

        except HTTPException:
            raise
        except Exception as e:
            logger.error(f"Failed to update order status: {str(e)}")
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Failed to update order status"
            )

    def _send_order_status_notification(self, order_id: UUID, order: Order, old_status: str, new_status: str, user_id: str, notes: str):
        """Notify the buyer when their order status changes."""
        notification_data = {
            "order_id": str(order_id),
            "old_status": old_status,
            "new_status": new_status,
            "updated_by": str(user_id),
            "notes": notes,
        }

        buyer_messages = {
            "processing": f"Your order #{str(order_id)[:8]} is now being processed.",
            "paid": f"Payment confirmed for your order #{str(order_id)[:8]}.",
            "shipped": f"Your order #{str(order_id)[:8]} has been shipped and is on its way.",
            "delivered": f"Your order #{str(order_id)[:8]} has been delivered!",
            "cancelled": f"Your order #{str(order_id)[:8]} has been cancelled.",
        }

        try:
            send_order_notification(
                user_id=str(order.buyer_id),
                order_id=str(order_id),
                status=new_status,
                message=buyer_messages.get(new_status, f"Your order #{str(order_id)[:8]} status changed to {new_status}."),
                is_seller=False,
                order_data=notification_data,
            )
        except Exception as e:
            logger.error(f"Failed to send buyer notification for order {order_id}: {e}")

        # Queue shipped/delivered emails to buyer
        if new_status in ("shipped", "delivered"):
            try:
                buyer_profile = order.buyer
                buyer_user = buyer_profile.user if buyer_profile else None
                if buyer_user:
                    items_summary = ", ".join(
                        f"{item.product.name} x{item.quantity}"
                        for item in order.order_items
                        if item.product
                    )
                    order_total = f"₦{sum(item.quantity * item.price for item in order.order_items):,.2f}"
                    if new_status == "shipped":
                        send_order_shipped_email.delay(
                            buyer_user.email,
                            buyer_profile.name or buyer_user.email,
                            str(order_id),
                            items_summary,
                            order_total,
                        )
                    else:
                        send_order_delivered_email.delay(
                            buyer_user.email,
                            buyer_profile.name or buyer_user.email,
                            str(order_id),
                            items_summary,
                            order_total,
                        )
            except Exception as e:
                logger.error(f"Failed to queue order {new_status} email for order {order_id}: {e}")

        logger.info(f"Order status notifications sent for order {order_id}: {old_status} -> {new_status}")

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
