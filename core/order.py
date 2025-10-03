from core.model import Order, OrderItem, Product
from sqlalchemy.orm import Session, joinedload
from sqlalchemy import UUID, func
from typing import List, Optional, Tuple, Dict
from schemas.order import OrderItemCreate
from core.inventory import inventory_service
from core.seller_payout_service import seller_payout_service
from fastapi import HTTPException, status
from decimal import Decimal
import logging
from contextlib import contextmanager
from copy import deepcopy

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
    
    def _with_relationships_and_sellers(self, query):
        """Helper to eager-load related entities including seller profiles for customer orders"""
        return query.options(
            joinedload(Order.buyer),
            joinedload(Order.order_items).joinedload(OrderItem.product).joinedload(Product.seller),
            joinedload(Order.delivery_addr),
            joinedload(Order.payments),
        )
    
    def _group_items_by_seller(self, order_items):
        """Group order items by seller and calculate totals"""
        from collections import defaultdict
        from schemas.products import SellerResponse
        from schemas.order import OrderItemResponse
        
        seller_groups = defaultdict(lambda: {
            'seller': None,
            'items': [],
            'total_amount': 0,
            'item_count': 0,
            'status': 'pending'  # Default status for seller group
        })
        
        for item in order_items:
            if item.product and item.product.seller:
                seller_id = item.product.seller.id
                seller_groups[seller_id]['seller'] = item.product.seller
                seller_groups[seller_id]['items'].append(item)
                seller_groups[seller_id]['total_amount'] += item.quantity * item.price
                seller_groups[seller_id]['item_count'] += item.quantity
                # TODO: Implement seller-specific status tracking
                # seller_groups[seller_id]['status'] = self._get_seller_status(order_id, seller_id)
        
        # Convert to properly serialized dictionaries
        result = []
        for group_data in seller_groups.values():
            # Serialize seller using SellerResponse schema
            seller_dict = None
            if group_data['seller']:
                seller_dict = SellerResponse.model_validate(group_data['seller']).model_dump()
            
            # Serialize items using OrderItemResponse schema
            items_dict = [OrderItemResponse.model_validate(item).model_dump() for item in group_data['items']]
            
            result.append({
                'seller': seller_dict,
                'items': items_dict,
                'total_amount': group_data['total_amount'],
                'item_count': group_data['item_count']
            })
        
        return result
    
    def calculate_overall_order_status(self, seller_statuses):
        """Calculate overall order status based on seller statuses"""
        if not seller_statuses:
            return 'pending'
            
        status_counts = {}
        for status in seller_statuses:
            status_counts[status] = status_counts.get(status, 0) + 1
        
        total_sellers = len(seller_statuses)
        
        # All delivered
        if status_counts.get('delivered', 0) == total_sellers:
            return 'delivered'
        
        # All cancelled
        if status_counts.get('cancelled', 0) == total_sellers:
            return 'cancelled'
        
        # Partial cancellation
        if status_counts.get('cancelled', 0) > 0:
            return 'partially_cancelled'
        
        # Partial delivery
        if status_counts.get('delivered', 0) > 0:
            return 'partially_delivered'
        
        # All shipped
        if status_counts.get('shipped', 0) == total_sellers:
            return 'shipped'
        
        # Partial shipping
        if status_counts.get('shipped', 0) > 0:
            return 'partially_shipped'
        
        # Any processing
        if status_counts.get('processing', 0) > 0:
            return 'processing'
        
        return 'pending'

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
    def fetch_orders(self, db: Session, limit: int = 10, page: int = 1, status: Optional[str] = None) -> Tuple[List[Order], int]:
        query = self._with_relationships(db.query(Order))
        if status:
            query = query.filter(Order.status == status)
        count = query.count()
        offset = (page - 1) * limit
        orders = query.offset(offset).limit(limit).all()
        return orders, count

    def get_order_by_id(self, db: Session, order_id: UUID, include_seller_groups: bool = False):
        if include_seller_groups:
            order = (
                self._with_relationships_and_sellers(db.query(Order))
                .filter(Order.id == order_id)
                .first()
            )
            if order:
                order.seller_groups = self._group_items_by_seller(order.order_items)
            return order
        else:
            return (
                self._with_relationships(db.query(Order))
                .filter(Order.id == order_id)
                .first()
            )

    def get_orders_by_buyer(self, db: Session, buyer_id: UUID, limit: int = 10, page: int = 1, status: Optional[str] = None) -> Tuple[List[Order], int]:
        query = self._with_relationships_and_sellers(
            db.query(Order)).filter(Order.buyer_id == buyer_id)
        if status:
            query = query.filter(Order.status == status)
        count = query.count()
        offset = (page - 1) * limit
        orders = query.offset(offset).limit(limit).all()
        
        # Group order items by seller for each order
        for order in orders:
            order.seller_groups = self._group_items_by_seller(order.order_items)
        
        return orders, count

    def get_orders_by_seller(self, db: Session, seller_id: UUID, limit: int = 10, page: int = 1, status: Optional[str] = None) -> Tuple[List[Order], int]:
        # Get ALL orders for this seller first
        query = (
            db.query(Order)
            .join(Order.order_items)
            .join(OrderItem.product)
            .filter(Product.seller_id == seller_id)
            .options(
                joinedload(Order.buyer),
                joinedload(Order.order_items).joinedload(OrderItem.product).joinedload(Product.images),
                joinedload(Order.order_items).joinedload(OrderItem.product).joinedload(Product.seller),
                joinedload(Order.order_items).joinedload(OrderItem.product).joinedload(Product.category),
                joinedload(Order.delivery_addr),
                joinedload(Order.payments),
            )
        )

        # Get all orders first
        all_orders = query.distinct(Order.id).all()

        # Filter items and calculate seller's portion for each order
        filtered_orders = []
        for order in all_orders:
            # Create a copy of the order to avoid modifying the original
            filtered_order = deepcopy(order)
            
            # Keep only items from this seller in the copy
            seller_items = [
                item for item in filtered_order.order_items 
                if item.product and str(item.product.seller_id) == str(seller_id)
            ]
            filtered_order.order_items = seller_items
            
            # Calculate seller's portion of the order total
            filtered_order.total_amount = sum(item.quantity * item.price for item in seller_items)
            
            # Calculate seller item status based on actual OrderItem statuses
            seller_items_for_status = [
                item for item in order.order_items 
                if item.product and str(item.product.seller_id) == str(seller_id)
            ]
            
            if not seller_items_for_status:
                # If no seller items found, check if order is cancelled
                if order.status == "cancelled":
                    filtered_order.seller_item_status = "cancelled"
                else:
                    filtered_order.seller_item_status = "pending"
            else:
                # Check if order is cancelled first - this takes priority
                if order.status == "cancelled":
                    filtered_order.seller_item_status = "cancelled"
                else:
                    # Use seller item statuses for non-cancelled orders
                    item_statuses = [item.status for item in seller_items_for_status]
                    
                    # If all items are cancelled, seller status is cancelled
                    if all(status == "cancelled" for status in item_statuses):
                        filtered_order.seller_item_status = "cancelled"
                    # If all items are delivered, seller status is delivered
                    elif all(status == "delivered" for status in item_statuses):
                        filtered_order.seller_item_status = "delivered"
                    # If all items are shipped, seller status is shipped
                    elif all(status == "shipped" for status in item_statuses):
                        filtered_order.seller_item_status = "shipped"
                    # If all items are processing, seller status is processing
                    elif all(status == "processing" for status in item_statuses):
                        filtered_order.seller_item_status = "processing"
                    # If all items are pending, seller status is pending
                    elif all(status == "pending" for status in item_statuses):
                        filtered_order.seller_item_status = "pending"
                    # Mixed statuses - determine the most advanced status
                    elif "delivered" in item_statuses:
                        filtered_order.seller_item_status = "delivered"
                    elif "shipped" in item_statuses:
                        filtered_order.seller_item_status = "shipped"
                    elif "processing" in item_statuses:
                        filtered_order.seller_item_status = "processing"
                    else:
                        filtered_order.seller_item_status = "pending"
            
            # Apply status filter based on seller_item_status
            if status and filtered_order.seller_item_status != status:
                continue
                
            filtered_orders.append(filtered_order)
        
        # Apply pagination AFTER filtering
        total_count = len(filtered_orders)
        offset = (page - 1) * limit
        paginated_orders = filtered_orders[offset:offset + limit]
            
        return paginated_orders, total_count

    def get_seller_order_by_id(self, db: Session, order_id: UUID, seller_id: UUID):
        """Get a specific order with only the seller's items"""
        order = (
            db.query(Order)
            .join(Order.order_items)
            .join(OrderItem.product)
            .filter(Order.id == order_id, Product.seller_id == seller_id)
            .options(
                joinedload(Order.buyer),
                joinedload(Order.order_items).joinedload(OrderItem.product).joinedload(Product.images),
                joinedload(Order.order_items).joinedload(OrderItem.product).joinedload(Product.seller),
                joinedload(Order.order_items).joinedload(OrderItem.product).joinedload(Product.category),
                joinedload(Order.delivery_addr),
                joinedload(Order.payments),
            )
            .first()
        )
        
        if order:
            # Create a copy of the order to avoid modifying the original
            filtered_order = deepcopy(order)
            
            # Keep only items from this seller in the copy
            seller_items = [
                item for item in filtered_order.order_items 
                if item.product and str(item.product.seller_id) == str(seller_id)
            ]
            filtered_order.order_items = seller_items
            
            # Calculate seller's portion of the order total
            filtered_order.total_amount = sum(item.quantity * item.price for item in seller_items)
            
            # Determine seller's item status based on order progression
            if seller_items:
                overall_status = order.status
                
                # Get all sellers in this order to understand multi-vendor context
                all_sellers = set()
                for item in order.order_items:
                    if item.product and item.product.seller_id:
                        all_sellers.add(str(item.product.seller_id))
                
                current_seller_id_str = str(seller_id)
                total_sellers = len(all_sellers)
                
                # Calculate seller item status based on actual OrderItem statuses
                seller_items = [
                    item for item in order.order_items 
                    if item.product and str(item.product.seller_id) == str(seller_id)
                ]
                
                if not seller_items:
                    # If no seller items found, check if order is cancelled
                    if order.status == "cancelled":
                        filtered_order.seller_item_status = "cancelled"
                    else:
                        filtered_order.seller_item_status = "pending"
                else:
                    # Check if order is cancelled first - this takes priority
                    if order.status == "cancelled":
                        filtered_order.seller_item_status = "cancelled"
                    else:
                        # Use seller item statuses for non-cancelled orders
                        item_statuses = [item.status for item in seller_items]
                        
                        # If all items are cancelled, seller status is cancelled
                        if all(status == "cancelled" for status in item_statuses):
                            filtered_order.seller_item_status = "cancelled"
                        # If all items are delivered, seller status is delivered
                        elif all(status == "delivered" for status in item_statuses):
                            filtered_order.seller_item_status = "delivered"
                        # If all items are shipped, seller status is shipped
                        elif all(status == "shipped" for status in item_statuses):
                            filtered_order.seller_item_status = "shipped"
                        # If all items are processing, seller status is processing
                        elif all(status == "processing" for status in item_statuses):
                            filtered_order.seller_item_status = "processing"
                        # If all items are pending, seller status is pending
                        elif all(status == "pending" for status in item_statuses):
                            filtered_order.seller_item_status = "pending"
                        # Mixed statuses - determine the most advanced status
                        elif "delivered" in item_statuses:
                            filtered_order.seller_item_status = "delivered"
                        elif "shipped" in item_statuses:
                            filtered_order.seller_item_status = "shipped"
                        elif "processing" in item_statuses:
                            filtered_order.seller_item_status = "processing"
                        else:
                            filtered_order.seller_item_status = "pending"
            else:
                filtered_order.seller_item_status = "pending"
            
            return filtered_order
            
        return order

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
                    status="pending"  # Initialize item status
                )
                db.add(order_item)
                db.flush()

                # Don't commit here - context manager handles it
                db.refresh(new_order)
                # Ensure total is consistent (already set), but recalc in case of float/decimal quirks
                recalc_total = sum(Decimal(str(i.price)) * i.quantity for i in new_order.order_items)
                new_order.total_amount = float(recalc_total)
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
                db.refresh(order)
                return order

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

    def get_valid_status_transitions(self, current_status: str, user_role: str = None) -> List[str]:
        """Get valid status transitions from current status"""
        transitions = {
            "pending": ["processing", "cancelled"],
            "processing": ["shipped", "cancelled"],
            "shipped": ["delivered"],
            "delivered": [],  # Final state
            "cancelled": []  # Final state
        }
        if user_role == "seller":
            # More flexible transitions for sellers until we implement item-level status
            transitions["pending"].append("shipped")
            transitions["processing"].append("delivered")
        return transitions.get(current_status, [])

    def validate_status_transition(self, current_status: str, new_status: str, user_role: str = None) -> bool:
        """Validate if status transition is allowed"""
        valid_transitions = self.get_valid_status_transitions(current_status, user_role)
        return new_status in valid_transitions

    def calculate_overall_order_status_from_items(self, order_items):
        """Calculate overall order status based on individual item statuses"""
        if not order_items:
            return 'pending'
        
        # Group items by seller and get their statuses
        seller_statuses = {}
        for item in order_items:
            if item.product and item.product.seller_id:
                seller_id = item.product.seller_id
                if seller_id not in seller_statuses:
                    seller_statuses[seller_id] = []
                seller_statuses[seller_id].append(item.status)
        
        # Determine each seller's overall status
        seller_overall_statuses = []
        for seller_id, item_statuses in seller_statuses.items():
            if all(status == 'delivered' for status in item_statuses):
                seller_overall_statuses.append('delivered')
            elif all(status == 'cancelled' for status in item_statuses):
                seller_overall_statuses.append('cancelled')
            elif any(status == 'shipped' for status in item_statuses):
                seller_overall_statuses.append('shipped')
            elif any(status == 'processing' for status in item_statuses):
                seller_overall_statuses.append('processing')
            else:
                seller_overall_statuses.append('pending')
        
        # Calculate overall order status from seller statuses
        return self.calculate_overall_order_status(seller_overall_statuses)

    def update_seller_items_status(
        self,
        db: Session,
        order_id: UUID,
        seller_id: UUID,
        new_status: str,
        notes: str = None
    ) -> Dict:
        """Update status for all items from a specific seller in an order"""
        try:
            with self.transaction_context(db):
                # Get order with relationships - use fresh query to ensure we have complete data
                order = (
                    db.query(Order)
                    .options(
                        joinedload(Order.buyer),
                        joinedload(Order.order_items).joinedload(OrderItem.product).joinedload(Product.seller),
                        joinedload(Order.order_items).joinedload(OrderItem.product).joinedload(Product.category),
                        joinedload(Order.delivery_addr),
                        joinedload(Order.payments),
                    )
                    .filter(Order.id == order_id)
                    .first()
                )
                if not order:
                    raise HTTPException(
                        status_code=status.HTTP_404_NOT_FOUND,
                        detail="Order not found"
                    )

                # Get seller's items in this order
                seller_items = [
                    item for item in order.order_items 
                    if item.product and str(item.product.seller_id) == str(seller_id)
                ]
                
                if not seller_items:
                    raise HTTPException(
                        status_code=status.HTTP_403_FORBIDDEN,
                        detail="You can only update orders containing your products"
                    )

                # Validate status transition for seller items
                current_item_status = seller_items[0].status  # Assume all seller items have same status
                if not self.validate_status_transition(current_item_status, new_status, "seller"):
                    valid_transitions = self.get_valid_status_transitions(current_item_status, "seller")
                    raise HTTPException(
                        status_code=status.HTTP_400_BAD_REQUEST,
                        detail=f"Invalid status transition from {current_item_status} to {new_status}. "
                        f"Valid transitions: {valid_transitions}"
                    )

                # Update all seller's items to new status
                for item in seller_items:
                    item.status = new_status
                    item.updated_at = func.current_timestamp()

                # Calculate new overall order status using ALL items (not just seller's items)
                # This ensures proper partial status calculation (partially_shipped, partially_delivered, etc.)
                new_order_status = self.calculate_overall_order_status_from_items(order.order_items)
                old_order_status = order.status
                order.status = new_order_status
                order.updated_at = func.current_timestamp()

                # Note: commit is handled by transaction_context

                return {
                    "order_id": str(order.id),
                    "seller_items_updated": len(seller_items),
                    "seller_items_status": new_status,
                    "previous_order_status": old_order_status,
                    "new_order_status": new_order_status,
                    "notes": notes
                }

        except HTTPException:
            raise
        except Exception as e:
            logger.error(f"Failed to update seller items status: {str(e)}")
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Failed to update seller items status"
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
                # Get order with relationships including seller info (needed for authorization)
                order = (
                    self._with_relationships_and_sellers(db.query(Order))
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
                if user_role == "seller":
                    # Check if seller has items in this order
                    seller_has_items = any(
                        str(item.product.seller_id) == str(user_id)
                        for item in order.order_items
                        if item.product and item.product.seller_id
                    )
                    
                    if not seller_has_items:
                        raise HTTPException(
                            status_code=status.HTTP_403_FORBIDDEN,
                            detail="You can only update orders containing your products"
                        )

                    # Check if order_items table has status column (for backward compatibility)
                    try:
                        # Try to use the new seller-specific method if status column exists
                        if hasattr(order.order_items[0], 'status'):
                            return self.update_seller_items_status(
                                db=db,
                                order_id=order_id,
                                seller_id=UUID(user_id),
                                new_status=new_status,
                                notes=notes
                            )
                    except (AttributeError, IndexError):
                        pass
                    
                    # Fallback: Update entire order status (temporary until DB is updated)
                    # Sellers can only mark orders as processing, shipped or delivered
                    if new_status not in ["processing", "shipped", "delivered"]:
                        raise HTTPException(
                            status_code=status.HTTP_403_FORBIDDEN,
                            detail="Sellers can only mark orders as processing, shipped or delivered"
                        )

                elif user_role == "customer":
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
                db.flush()  # Ensure changes are written to DB
                db.refresh(order)

                # Update seller balances for this order
                self.update_seller_balances_for_order(db, order_id, new_status)

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
    
    def update_seller_balances_for_order(self, db: Session, order_id: UUID, new_status: str):
        """
        Update seller balances when order status changes
        
        Args:
            db: Database session
            order_id: Order ID
            new_status: New order status
        """
        try:
            # Get all sellers involved in this order
            order_items = (
                db.query(OrderItem)
                .join(Product)
                .filter(OrderItem.order_id == order_id)
                .all()
            )
            
            # Group by seller
            sellers_involved = set()
            for item in order_items:
                if item.product and item.product.seller_id:
                    sellers_involved.add(str(item.product.seller_id))
            
            # Update balance for each seller
            for seller_id in sellers_involved:
                seller_payout_service.update_seller_balance(
                    db=db,
                    seller_id=seller_id,
                    order_id=str(order_id),
                    order_status=new_status
                )
                
            logger.info(f"Updated seller balances for order {order_id} with status {new_status}")
            
        except Exception as e:
            logger.error(f"Failed to update seller balances for order {order_id}: {e}")


order_service = OrderService()
