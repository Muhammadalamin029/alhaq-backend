from core.model import Product
from sqlalchemy.orm import Session
from sqlalchemy import UUID
import logging


class ProductService:
    def __init__(self):
        pass

    def fetch_products(self, db: Session):
        try:
            products = db.query(Product).all()
            return products
        except Exception as e:
            logging.error(f"Error fetching products: {e}")
            return []

    def add_product(self, db: Session, name: str, price: float, user_id: UUID, category_id: UUID, description: str, stock_quantity: int, image_url: str = None):
        try:
            new_product = Product(name=name, price=price, seller_id=user_id, category_id=category_id,
                                  description=description, stock_quantity=stock_quantity, image_url=image_url)
            db.add(new_product)
            db.commit()
            db.refresh(new_product)
            return new_product
        except Exception as e:
            logging.error(f"Error adding product: {e}")
            db.rollback()
            return None

    def get_product_by_id(self, db: Session, product_id: UUID):
        try:
            product = db.query(Product).filter(
                Product.id == product_id).first()
            return product
        except Exception as e:
            logging.error(f"Error fetching product by ID: {e}")
            return None

    def get_products_by_seller(self, db: Session, seller_id: UUID):
        try:
            products = db.query(Product).filter(
                Product.seller_id == seller_id).all()
            return products
        except Exception as e:
            logging.error(f"Error fetching products by seller ID: {e}")
            return []

    def get_products_by_category(self, db: Session, category_id: UUID):
        try:
            products = db.query(Product).filter(
                Product.category_id == category_id).all()
            return products
        except Exception as e:
            logging.error(f"Error fetching products by category ID: {e}")
            return []

    def update_product_stock(self, db: Session, product_id: UUID, new_stock: int):
        try:
            product = db.query(Product).filter(
                Product.id == product_id).first()
            if product:
                product.stock_quantity = new_stock
                db.commit()
                db.refresh(product)
                return product
            return None
        except Exception as e:
            logging.error(f"Error updating product stock: {e}")
            db.rollback()
            return None

    def delete_product(self, db: Session, product_id: UUID):
        try:
            product = db.query(Product).filter(
                Product.id == product_id).first()
            if product:
                db.delete(product)
                db.commit()
                return True
            return False
        except Exception as e:
            logging.error(f"Error deleting product: {e}")
            db.rollback()
            return False

    def update_product(self, db: Session, product_id: UUID, **kwargs):
        try:
            product = db.query(Product).filter(
                Product.id == product_id).first()
            if product:
                for key, value in kwargs.items():
                    setattr(product, key, value)
                db.commit()
                db.refresh(product)
                return product
            return None
        except Exception as e:
            logging.error(f"Error updating product: {e}")
            db.rollback()
            return None


product_service = ProductService()
