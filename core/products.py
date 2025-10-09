from core.model import Product, ProductImage
from sqlalchemy.orm import Session, joinedload
from sqlalchemy import UUID
from schemas.products import ProductImageSchema
from typing import Optional


class ProductService:
    def _with_relationships(self, query):
        """Helper to always eager-load seller, category, and images"""
        return query.options(
            joinedload(Product.seller),
            joinedload(Product.category),
            joinedload(Product.images)
        )

    def fetch_products(self, db: Session, search_query: Optional[str] = None, category_id: Optional[str] = None, limit: int = 10, page: int = 1):

        query = self._with_relationships(db.query(Product))

        if search_query:
            query = query.filter(Product.name.ilike(f"%{search_query}%"))

        if category_id:
            query = query.filter(Product.category_id == category_id)

        offset = (page - 1) * limit
        count = query.count()
        products = query.offset(offset).limit(limit).all()
        return products, count

    def add_product(
        self,
        db: Session,
        name: str,
        price: float,
        user_id: UUID,
        category_id: UUID,
        description: Optional[str] = None,
        stock_quantity: int = 0,
        images: Optional[list] = None
    ):
        # 1. Create product with default status
        new_product = Product(
            name=name,
            price=price,
            seller_id=user_id,
            category_id=category_id,
            description=description,
            stock_quantity=stock_quantity,
            status="active" if stock_quantity > 0 else "out_of_stock"
        )
        db.add(new_product)
        db.flush()  # assign ID

        # 2. Add images if provided
        if images:
            for img in images:
                product_image = ProductImage(
                    product_id=new_product.id,
                    image_url=img.image_url
                )
                db.add(product_image)

        db.commit()
        db.refresh(new_product)

        # 3. Eager load relationships for response
        return db.query(Product).options(
            joinedload(Product.seller),
            joinedload(Product.category),
            joinedload(Product.images)
        ).filter(Product.id == new_product.id).first()

    def get_product_by_id(self, db: Session, product_id: UUID):
        return (
            self._with_relationships(db.query(Product))
            .filter(Product.id == product_id)
            .first()
        )

    def get_products_by_seller(
        self, db: Session, seller_id: UUID, limit: int = 10, page: int = 1
    ):
        query = self._with_relationships(db.query(Product)).filter(
            Product.seller_id == seller_id
        )

        count = query.count()
        offset = (page - 1) * limit

        products = query.offset(offset).limit(limit).all()

        return products, count

    def update_product_stock(self, db: Session, product_id: UUID, new_stock: int):
        product = db.query(Product).filter(Product.id == product_id).first()
        if not product:
            return None
        product.stock_quantity = new_stock
        db.commit()
        db.refresh(product)
        return self.get_product_by_id(db, product.id)

    def delete_product(self, db: Session, product_id: UUID):
        from core.logging_config import get_logger
        logger = get_logger(__name__)
        
        product = db.query(Product).filter(Product.id == product_id).first()
        if not product:
            logger.warning(f"Product {product_id} not found for deletion")
            return False
        
        # Check if product has any order items (financial records)
        from core.model import OrderItem
        existing_order_items = db.query(OrderItem).filter(OrderItem.product_id == product_id).first()
        
        if existing_order_items:
            # If product has order history, mark as inactive instead of deleting
            logger.info(f"Product {product_id} has order history, marking as inactive instead of deleting")
            product.status = "inactive"
            product.name = f"[DELETED] {product.name}"  # Mark as deleted for reference
            db.commit()
            db.refresh(product)
            return True
        else:
            # Safe to delete - no order history
            logger.info(f"Product {product_id} has no order history, proceeding with deletion")
            db.delete(product)
            db.commit()
            return True

    def update_product(self, db: Session, product_id: UUID, **kwargs):
        from core.logging_config import get_logger
        logger = get_logger(__name__)
        
        logger.info(f"update_product called with product_id: {product_id}, kwargs: {kwargs}")
        
        product = db.query(Product).filter(Product.id == product_id).first()
        if not product:
            logger.error(f"Product {product_id} not found")
            return None
            
        logger.info(f"Found product: {product.name} (ID: {product.id})")
        
        for key, value in kwargs.items():
            old_value = getattr(product, key, None)
            setattr(product, key, value)
            logger.info(f"Updated {key}: {old_value} -> {value}")
            
        logger.info("Committing changes to database...")
        try:
            db.commit()
            db.refresh(product)
            logger.info(f"Product updated successfully: {product.name}")
            return self.get_product_by_id(db, product.id)
        except Exception as commit_error:
            logger.error(f"Error committing product update: {str(commit_error)}")
            db.rollback()
            raise commit_error


product_service = ProductService()
