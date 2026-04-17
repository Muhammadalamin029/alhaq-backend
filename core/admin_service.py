from sqlalchemy.orm import Session
from core.model import Product, Car, Property, Phone
from typing import Dict, Optional
from uuid import UUID

class AdminService:
    @staticmethod
    def get_asset_counts(db: Session, seller_id: Optional[UUID] = None) -> Dict[str, int]:
        """
        Fetch counts for all asset types, optionally filtered by seller.
        Returns a breakdown by category.
        """
        p_query = db.query(Product)
        c_query = db.query(Car)
        pr_query = db.query(Property)
        ph_query = db.query(Phone)

        if seller_id:
            p_query = p_query.filter(Product.seller_id == seller_id)
            c_query = c_query.filter(Car.seller_id == seller_id)
            pr_query = pr_query.filter(Property.seller_id == seller_id)
            ph_query = ph_query.filter(Phone.seller_id == seller_id)

        return {
            "products": p_query.count(),
            "cars": c_query.count(),
            "properties": pr_query.count(),
            "phones": ph_query.count()
        }

    @staticmethod
    def get_seller_total_count(db: Session, seller_id: UUID) -> int:
        """
        Returns the unified total count of all inventory items for a specific seller.
        Summing all categories handles different seller types automatically.
        """
        counts = AdminService.get_asset_counts(db, seller_id=seller_id)
        return sum(counts.values())

admin_service = AdminService()
