from core.model import Product
from sqlalchemy.orm import Session, joinedload
from sqlalchemy import UUID


class ProductService:
    def _with_relationships(self, query):
        """Helper to always eager-load seller and category"""
        return query.options(
            joinedload(Product.seller),
            joinedload(Product.category)
        )

    def fetch_products(self, db: Session):
        return self._with_relationships(db.query(Product)).all()

    def add_product(
        self, db: Session, name: str, price: float, user_id: UUID,
        category_id: UUID, description: str, stock_quantity: int,
        image_url: str = None
    ):
        new_product = Product(
            name=name,
            price=price,
            seller_id=user_id,
            category_id=category_id,
            description=description,
            stock_quantity=stock_quantity,
            image_url=image_url
        )
        db.add(new_product)
        db.commit()
        db.refresh(new_product)
        # reload with relationships
        return self.get_product_by_id(db, new_product.id)

    def get_product_by_id(self, db: Session, product_id: UUID):
        return (
            self._with_relationships(db.query(Product))
            .filter(Product.id == product_id)
            .first()
        )

    def get_products_by_seller(self, db: Session, seller_id: UUID):
        return (
            self._with_relationships(db.query(Product))
            .filter(Product.seller_id == seller_id)
            .all()
        )

    def get_products_by_category(self, db: Session, category_id: UUID):
        return (
            self._with_relationships(db.query(Product))
            .filter(Product.category_id == category_id)
            .all()
        )

    def update_product_stock(self, db: Session, product_id: UUID, new_stock: int):
        product = db.query(Product).filter(Product.id == product_id).first()
        if not product:
            return None
        product.stock_quantity = new_stock
        db.commit()
        db.refresh(product)
        return self.get_product_by_id(db, product.id)

    def delete_product(self, db: Session, product_id: UUID):
        product = db.query(Product).filter(Product.id == product_id).first()
        if not product:
            return False
        db.delete(product)
        db.commit()
        return True

    def update_product(self, db: Session, product_id: UUID, **kwargs):
        product = db.query(Product).filter(Product.id == product_id).first()
        if not product:
            return None
        for key, value in kwargs.items():
            setattr(product, key, value)
        db.commit()
        db.refresh(product)
        return self.get_product_by_id(db, product.id)


product_service = ProductService()
