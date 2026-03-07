from sqlalchemy.orm import Session
from uuid import UUID
from datetime import datetime
from typing import List, Optional
from fastapi import HTTPException
from core.model import Phone, PhoneUnit, AssetImage
from schemas.phone import PhoneCreate, PhoneUpdate

class PhoneService:
    def create_phone(self, db: Session, seller_id: UUID, phone_data: PhoneCreate) -> Phone:
        # Check if any IMEI already exists
        imeis = [u.imei for u in phone_data.units]
        existing = db.query(PhoneUnit).filter(PhoneUnit.imei.in_(imeis)).first()
        if existing:
            raise HTTPException(status_code=400, detail=f"IMEI {existing.imei} already exists")

        phone_listing = Phone(
            seller_id=seller_id,
            brand=phone_data.brand,
            model=phone_data.model,
            specs=phone_data.specs,
            price=phone_data.price,
            min_deposit_percentage=phone_data.min_deposit_percentage,
            status="available"
        )
        db.add(phone_listing)
        db.flush()

        for unit_data in phone_data.units:
            unit = PhoneUnit(
                phone_id=phone_listing.id,
                imei=unit_data.imei,
                color=unit_data.color,
                grade=unit_data.grade,
                battery_health=unit_data.battery_health,
                status="available"
            )
            db.add(unit)

        if phone_data.images:
            for img_data in phone_data.images:
                img = AssetImage(
                    phone_id=phone_listing.id,
                    image_url=img_data.image_url
                )
                db.add(img)

        db.commit()
        db.refresh(phone_listing)
        return phone_listing

    def list_phones(self, db: Session, seller_id: UUID = None) -> List[Phone]:
        query = db.query(Phone)
        if seller_id:
            query = query.filter(Phone.seller_id == seller_id)
        return query.order_by(Phone.created_at.desc()).all()

    def get_phone(self, db: Session, phone_id: UUID) -> Optional[Phone]:
        return db.query(Phone).filter(Phone.id == phone_id).first()

    def update_phone(self, db: Session, phone_id: UUID, seller_id: UUID, update_data: PhoneUpdate) -> Phone:
        phone = db.query(Phone).filter(Phone.id == phone_id, Phone.seller_id == seller_id).first()
        if not phone:
            raise HTTPException(status_code=404, detail="Phone not found or unauthorized")
        
        update_dict = update_data.model_dump(exclude_unset=True)
        
        if "images" in update_dict:
            # Remove existing images
            db.query(AssetImage).filter(AssetImage.phone_id == phone_id).delete()
            
            # Add new images
            images_data = update_dict.pop("images")
            if images_data:
                for img_data in images_data:
                    img = AssetImage(
                        phone_id=phone_id,
                        image_url=img_data["image_url"] if isinstance(img_data, dict) else img_data.image_url
                    )
                    db.add(img)

        for key, value in update_dict.items():
            setattr(phone, key, value)
            
        db.commit()
        db.refresh(phone)
        return phone

    def add_units_to_listing(self, db: Session, phone_id: UUID, seller_id: UUID, units_data: List[PhoneUnitCreate]) -> List[PhoneUnit]:
        phone = db.query(Phone).filter(Phone.id == phone_id, Phone.seller_id == seller_id).first()
        if not phone:
            raise HTTPException(status_code=404, detail="Phone listing not found or unauthorized")

        # Check IMEI uniqueness
        imeis = [u.imei for u in units_data]
        existing = db.query(PhoneUnit).filter(PhoneUnit.imei.in_(imeis)).first()
        if existing:
            raise HTTPException(status_code=400, detail=f"IMEI {existing.imei} already exists")

        new_units = []
        for unit_data in units_data:
            # Handle both Pydantic model and dict
            data = unit_data.model_dump() if hasattr(unit_data, 'model_dump') else unit_data
            
            unit = PhoneUnit(
                phone_id=phone_id,
                imei=data['imei'],
                color=data.get('color'),
                grade=data.get('grade'),
                battery_health=data.get('battery_health'),
                status="available"
            )
            db.add(unit)
            new_units.append(unit)

        # If listing was out of stock, mark it as available again
        if phone.status == "out_of_stock":
            phone.status = "available"

        db.commit()
        for u in new_units:
            db.refresh(u)
        return new_units

phone_service = PhoneService()
