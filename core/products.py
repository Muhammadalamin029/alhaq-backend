from core.model import Product, ProductImage
from sqlalchemy.orm import Session, joinedload
from sqlalchemy import UUID
from schemas.products import ProductImage


class ProductService:
    def _with_relationships(self, query):
        """Helper to always eager-load seller and category"""
        return query.options(
            joinedload(Product.seller),
            joinedload(Product.category)
        )

    def fetch_products(self, db: Session):
        return self._with_relationships(db.query(Product)).limit(10).all()

    def search_products(self, db: Session, keyword: str):
        return (
            self._with_relationships(db.query(Product))
            .filter(Product.name.ilike(f"%{keyword}%"))
            .all()
        )

    def add_product(
        self,
        db: Session,
        name: str,
        price: float,
        user_id: UUID,
        category_id: UUID,
        description: str,
        stock_quantity: int,
        images: list[ProductImage] = None
    ):
        # 1. Create the product
        new_product = Product(
            name=name,
            price=price,
            seller_id=user_id,
            category_id=category_id,
            description=description,
            stock_quantity=stock_quantity,
        )
        db.add(new_product)
        db.flush()  # Get the product ID before committing

        # 2. Add images if provided
        if images:
            for img in images:
                product_image = ProductImage(
                    product_id=new_product.id,
                    image_url=img.url
                )
                db.add(product_image)

        # 3. Commit everything once
        db.commit()
        db.refresh(new_product)

        # 4. Return the product with relationships loaded
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
            .limit(10)
            .all()
        )

    def get_products_by_category(self, db: Session, category_id: UUID):
        return (
            self._with_relationships(db.query(Product))
            .filter(Product.category_id == category_id)
            .limit(10)
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
