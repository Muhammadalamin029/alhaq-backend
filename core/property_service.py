from sqlalchemy.orm import Session
from uuid import UUID
from datetime import datetime
from typing import List, Optional
from fastapi import HTTPException
from core.model import Property, AssetImage, PropertyUnit, GeneralInspection
from schemas.property import PropertyCreate, PropertyUpdate

class PropertyService:
    def create_property(self, db: Session, seller_id: UUID, property_data: PropertyCreate) -> Property:
        new_property = Property(
            seller_id=seller_id,
            title=property_data.title,
            description=property_data.description,
            price=property_data.price,
            location=property_data.location,
            listing_type=property_data.listing_type,
            buildings_count=property_data.buildings_count or 1,
            bedrooms=property_data.bedrooms,
            bathrooms=property_data.bathrooms,
            square_feet=property_data.square_feet,
            status="available"
        )
        db.add(new_property)
        db.flush()

        # Create Property Units
        if property_data.units:
            for u in property_data.units:
                unit = PropertyUnit(
                    property_id=new_property.id,
                    unit_name=u.unit_name or "Unit",
                    unit_number=u.unit_number,
                    status="available"
                )
                db.add(unit)
        else:
            num_units = property_data.buildings_count or 1
            for i in range(num_units):
                unit = PropertyUnit(
                    property_id=new_property.id,
                    unit_name=f"Unit {i+1}" if num_units > 1 else "Main Unit",
                    status="available"
                )
                db.add(unit)

        if property_data.images:
            for img_data in property_data.images:
                img = AssetImage(
                    property_id=new_property.id,
                    image_url=img_data.image_url
                )
                db.add(img)

        db.commit()
        db.refresh(new_property)
        return new_property

    def list_properties(self, db: Session, seller_id: UUID = None, status: str = "available") -> List[Property]:
        query = db.query(Property)
        if seller_id:
            query = query.filter(Property.seller_id == seller_id)
        if status:
            query = query.filter(Property.status == status)
        return query.order_by(Property.created_at.desc()).all()

    def get_property(self, db: Session, property_id: UUID) -> Optional[Property]:
        return db.query(Property).filter(Property.id == property_id).first()

    def update_property(self, db: Session, property_id: UUID, seller_id: UUID, update_data: PropertyUpdate) -> Property:
        prop = db.query(Property).filter(Property.id == property_id, Property.seller_id == seller_id).first()
        if not prop:
            raise HTTPException(status_code=404, detail="Property not found or unauthorized")
        
        update_dict = update_data.model_dump(exclude_unset=True)
        
        if "images" in update_dict:
            # Remove existing images
            db.query(AssetImage).filter(AssetImage.property_id == property_id).delete()
            
            # Add new images
            images_data = update_dict.pop("images")
            if images_data:
                for img_data in images_data:
                    img = AssetImage(
                        property_id=property_id,
                        image_url=img_data["image_url"] if isinstance(img_data, dict) else img_data.image_url
                    )
                    db.add(img)

        for key, value in update_dict.items():
            setattr(prop, key, value)
            
        db.commit()
        db.refresh(prop)
        return prop

    def list_internal_inventory(self, db: Session) -> List[Property]:
        # Internal inventory properties are those starting with [ACQUIRED] or held by platform
        # For now, let's filter by title or another flag if we had one.
        # Ideally we'd have an 'is_internal' flag.
        return db.query(Property).filter(Property.status == "acquired").all()

property_service = PropertyService()
