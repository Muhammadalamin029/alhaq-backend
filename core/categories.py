from core.model import Category
from sqlalchemy.orm import Session
from sqlalchemy import UUID


class CategoryService:
    def fetch_categories(self, db: Session, limit: int = 10, page: int = 1):
        offset = (page - 1) * limit
        query = db.query(Category)
        count = query.count()
        categories = query.offset(offset).limit(limit).all()
        return categories, count

    def add_category(self, db: Session, name: str, description: str = None):
        # Check if category with same name already exists
        existing = self.get_category_by_name(db, name)
        if existing:
            raise ValueError("Category name already exists")
        
        new_category = Category(name=name, description=description)
        db.add(new_category)
        db.commit()
        db.refresh(new_category)
        return new_category

    def get_category_by_id(self, db: Session, category_id: UUID):
        return db.query(Category).filter(Category.id == category_id).first()

    def get_category_by_name(self, db: Session, name: str):
        return db.query(Category).filter(Category.name == name).first()

    def update_category(self, db: Session, category_id: UUID, **kwargs):
        category = db.query(Category).filter(
            Category.id == category_id).first()
        if not category:
            return None
        for key, value in kwargs.items():
            setattr(category, key, value)
        db.commit()
        db.refresh(category)
        return category

    def delete_category(self, db: Session, category_id: UUID):
        category = db.query(Category).filter(
            Category.id == category_id).first()
        if not category:
            return False
        db.delete(category)
        db.commit()
        return True


category_service = CategoryService()
