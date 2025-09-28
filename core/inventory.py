from sqlalchemy.orm import Session
from sqlalchemy import UUID, select, func
from core.model import Product, Order, OrderItem
from typing import Dict, List, Optional, Tuple
from fastapi import HTTPException, status
from decimal import Decimal
import logging
from contextlib import contextmanager

logger = logging.getLogger(__name__)


class InventoryService:
    """Centralized inventory and stock management service"""

    @contextmanager
    def transaction_context(self, db: Session):
        """Context manager for database transactions with proper rollback"""
        try:
            yield db
            db.commit()
        except Exception as e:
            db.rollback()
            logger.error(f"Transaction failed: {str(e)}")
            raise

    def check_product_availability(self, db: Session, product_id: UUID, requested_quantity: int) -> Dict:
        """
        Check if a product is available for purchase
        
        Args:
            db: Database session
            product_id: Product UUID
            requested_quantity: Quantity requested
            
        Returns:
            Dict with availability info and product details
        """
        product = db.query(Product).filter(Product.id == product_id).first()
        
        if not product:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Product not found"
            )
        
        if product.status != "active":
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Product is {product.status} and not available for purchase"
            )
        
        available_stock = product.stock_quantity
        is_available = available_stock >= requested_quantity
        
        return {
            "product": product,
            "is_available": is_available,
            "available_stock": available_stock,
            "requested_quantity": requested_quantity,
            "shortage": max(0, requested_quantity - available_stock)
        }

    def reserve_stock(self, db: Session, product_id: UUID, quantity: int, order_id: UUID = None) -> bool:
        """
        Reserve stock for an order (decrement available stock)
        
        Args:
            db: Database session
            product_id: Product UUID
            quantity: Quantity to reserve
            order_id: Order UUID for logging
            
        Returns:
            bool: True if successful
        """
        with self.transaction_context(db):
            # Lock the product row for update
            product = db.query(Product).filter(Product.id == product_id).with_for_update().first()
            
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
            
            # Decrement stock
            product.stock_quantity -= quantity
            
            # Update product status if out of stock
            if product.stock_quantity == 0:
                product.status = "out_of_stock"
            
            logger.info(f"Reserved {quantity} units of product {product_id} for order {order_id}")
            return True

    def release_stock(self, db: Session, product_id: UUID, quantity: int, order_id: UUID = None) -> bool:
        """
        Release reserved stock back to available inventory
        
        Args:
            db: Database session
            product_id: Product UUID
            quantity: Quantity to release
            order_id: Order UUID for logging
            
        Returns:
            bool: True if successful
        """
        with self.transaction_context(db):
            # Lock the product row for update
            product = db.query(Product).filter(Product.id == product_id).with_for_update().first()
            
            if not product:
                logger.warning(f"Product {product_id} not found when releasing stock")
                return False
            
            # Increment stock
            product.stock_quantity += quantity
            
            # Update product status if it was out of stock
            if product.status == "out_of_stock" and product.stock_quantity > 0:
                product.status = "active"
            
            logger.info(f"Released {quantity} units of product {product_id} from order {order_id}")
            return True

    def reserve_multiple_products(self, db: Session, items: List[Dict], order_id: UUID = None) -> bool:
        """
        Reserve stock for multiple products atomically
        
        Args:
            db: Database session
            items: List of dicts with 'product_id' and 'quantity'
            order_id: Order UUID for logging
            
        Returns:
            bool: True if all reservations successful
        """
        try:
            with self.transaction_context(db):
                reserved_items = []
                
                # First, check availability for all items
                for item in items:
                    availability = self.check_product_availability(
                        db, item['product_id'], item['quantity']
                    )
                    if not availability['is_available']:
                        raise HTTPException(
                            status_code=status.HTTP_400_BAD_REQUEST,
                            detail=f"Insufficient stock for product {item['product_id']}. "
                                   f"Available: {availability['available_stock']}, "
                                   f"Requested: {item['quantity']}"
                        )
                
                # If all items are available, reserve them
                for item in items:
                    # Use a direct approach without calling reserve_stock to avoid nested transactions
                    product = db.query(Product).filter(
                        Product.id == item['product_id']
                    ).with_for_update().first()
                    
                    product.stock_quantity -= item['quantity']
                    if product.stock_quantity == 0:
                        product.status = "out_of_stock"
                    
                    reserved_items.append({
                        'product_id': item['product_id'],
                        'quantity': item['quantity']
                    })
                
                logger.info(f"Reserved stock for {len(reserved_items)} products for order {order_id}")
                return True
                
        except Exception as e:
            logger.error(f"Failed to reserve multiple products for order {order_id}: {str(e)}")
            raise

    def release_multiple_products(self, db: Session, items: List[Dict], order_id: UUID = None) -> bool:
        """
        Release stock for multiple products atomically
        
        Args:
            db: Database session
            items: List of dicts with 'product_id' and 'quantity'
            order_id: Order UUID for logging
            
        Returns:
            bool: True if all releases successful
        """
        try:
            with self.transaction_context(db):
                for item in items:
                    product = db.query(Product).filter(
                        Product.id == item['product_id']
                    ).with_for_update().first()
                    
                    if product:
                        product.stock_quantity += item['quantity']
                        if product.status == "out_of_stock" and product.stock_quantity > 0:
                            product.status = "active"
                
                logger.info(f"Released stock for {len(items)} products from order {order_id}")
                return True
                
        except Exception as e:
            logger.error(f"Failed to release multiple products for order {order_id}: {str(e)}")
            raise

    def get_low_stock_products(self, db: Session, threshold: int = 10, seller_id: UUID = None) -> List[Product]:
        """
        Get products with low stock levels
        
        Args:
            db: Database session
            threshold: Stock level threshold
            seller_id: Optional seller filter
            
        Returns:
            List of products with low stock
        """
        query = db.query(Product).filter(Product.stock_quantity <= threshold)
        
        if seller_id:
            query = query.filter(Product.seller_id == seller_id)
        
        return query.all()

    def get_stock_report(self, db: Session, seller_id: UUID = None) -> Dict:
        """
        Generate stock report
        
        Args:
            db: Database session
            seller_id: Optional seller filter
            
        Returns:
            Dict with stock statistics
        """
        query = db.query(Product)
        if seller_id:
            query = query.filter(Product.seller_id == seller_id)
        
        products = query.all()
        
        total_products = len(products)
        total_stock = sum(p.stock_quantity for p in products)
        out_of_stock = len([p for p in products if p.stock_quantity == 0])
        low_stock = len([p for p in products if 0 < p.stock_quantity <= 10])
        
        return {
            "total_products": total_products,
            "total_stock_units": total_stock,
            "out_of_stock_count": out_of_stock,
            "low_stock_count": low_stock,
            "average_stock_per_product": total_stock / total_products if total_products > 0 else 0
        }

    def update_product_stock_status(self, db: Session, product_id: UUID) -> bool:
        """
        Update product status based on current stock level
        
        Args:
            db: Database session
            product_id: Product UUID
            
        Returns:
            bool: True if updated successfully
        """
        try:
            with self.transaction_context(db):
                product = db.query(Product).filter(Product.id == product_id).first()
                
                if not product:
                    return False
                
                old_status = product.status
                
                if product.stock_quantity == 0:
                    product.status = "out_of_stock"
                elif product.status == "out_of_stock" and product.stock_quantity > 0:
                    product.status = "active"
                
                if old_status != product.status:
                    logger.info(f"Product {product_id} status changed from {old_status} to {product.status}")
                
                return True
                
        except Exception as e:
            logger.error(f"Failed to update product status for {product_id}: {str(e)}")
            return False

    def validate_order_items_stock(self, db: Session, order_items: List[Dict]) -> Tuple[bool, List[str]]:
        """
        Validate stock availability for all items in an order
        
        Args:
            db: Database session
            order_items: List of dicts with 'product_id' and 'quantity'
            
        Returns:
            Tuple of (is_valid, list_of_errors)
        """
        errors = []
        is_valid = True
        
        for item in order_items:
            try:
                availability = self.check_product_availability(
                    db, item['product_id'], item['quantity']
                )
                if not availability['is_available']:
                    errors.append(
                        f"Product {item['product_id']}: Insufficient stock "
                        f"(Available: {availability['available_stock']}, "
                        f"Requested: {item['quantity']})"
                    )
                    is_valid = False
            except HTTPException as e:
                errors.append(f"Product {item['product_id']}: {e.detail}")
                is_valid = False
        
        return is_valid, errors


# Global inventory service instance
inventory_service = InventoryService()