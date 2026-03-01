from sqlalchemy.orm import Session
from sqlalchemy import or_
from uuid import UUID
from datetime import datetime
from typing import List, Optional, Dict, Any
from fastapi import HTTPException, status

from core.model import Car, CarUnit, User, SellerProfile, AssetImage
from schemas.automotive import CarCreate, CarUpdate, CarUnitCreate, CarUnitUpdate
from core.notifications_service import create_notification
from decimal import Decimal

class AutomotiveService:
    def delete_car_unit(self, db: Session, unit_id: UUID, seller_id: UUID) -> bool:
        unit = db.query(CarUnit).join(Car).filter(CarUnit.id == unit_id, Car.seller_id == seller_id).first()
        if not unit:
            raise HTTPException(status_code=404, detail="Car unit not found or unauthorized")
        
        db.delete(unit)
        db.commit()
        return True

    def delete_car(self, db: Session, car_id: UUID, seller_id: UUID) -> bool:
        car = db.query(Car).filter(Car.id == car_id, Car.seller_id == seller_id).first()
        if not car:
            raise HTTPException(status_code=404, detail="Car listing not found or unauthorized")
        
        db.delete(car) # Cascade will handle units and images
        db.commit()
        return True

    def update_car_unit(self, db: Session, unit_id: UUID, seller_id: UUID, update_data: CarUnitUpdate) -> CarUnit:
        unit = db.query(CarUnit).join(Car).filter(CarUnit.id == unit_id, Car.seller_id == seller_id).first()
        if not unit:
            raise HTTPException(status_code=404, detail="Car unit not found or unauthorized")
        
        update_dict = update_data.model_dump(exclude_unset=True)
        for key, value in update_dict.items():
            setattr(unit, key, value)
            
        db.commit()
        db.refresh(unit)
        return unit

    def create_car(self, db: Session, seller_id: UUID, car_data: CarCreate) -> Car:
        # Check if any VIN already exists
        vins = [u.vin for u in car_data.units]
        existing = db.query(CarUnit).filter(CarUnit.vin.in_(vins)).first()
        if existing:
            raise HTTPException(status_code=400, detail=f"VIN {existing.vin} already exists")

        car_listing = Car(
            seller_id=seller_id,
            brand=car_data.brand,
            model=car_data.model,
            year=car_data.year,
            price=car_data.price,
            min_deposit_percentage=car_data.min_deposit_percentage,
            status="available"
        )
        db.add(car_listing)
        db.flush()

        for unit_data in car_data.units:
            unit = CarUnit(
                car_id=car_listing.id,
                vin=unit_data.vin,
                mileage=unit_data.mileage,
                color=unit_data.color,
                status="available"
            )
            db.add(unit)

        if car_data.images:
            for img_data in car_data.images:
                img = AssetImage(
                    car_id=car_listing.id,
                    image_url=img_data.image_url
                )
                db.add(img)

        db.commit()
        db.refresh(car_listing)
        return car_listing


    def get_car(self, db: Session, car_id: UUID) -> Optional[Car]:
        return db.query(Car).filter(Car.id == car_id).first()

    def list_cars(self, db: Session, 
                 brand: Optional[str] = None, 
                 model: Optional[str] = None, 
                 status: Optional[str] = None,
                 min_price: Optional[float] = None,
                 max_price: Optional[float] = None,
                 seller_id: Optional[UUID] = None) -> List[Car]:
        query = db.query(Car)
        
        if brand:
            query = query.filter(Car.brand.ilike(f"%{brand}%"))
        if model:
            query = query.filter(Car.model.ilike(f"%{model}%"))
        if status:
            query = query.filter(Car.status == status)
        if min_price:
            query = query.filter(Car.price >= min_price)
        if max_price:
            query = query.filter(Car.price <= max_price)
        if seller_id:
            query = query.filter(Car.seller_id == seller_id)
            
        return query.order_by(Car.created_at.desc()).all()

    def update_car(self, db: Session, car_id: UUID, seller_id: UUID, update_data: CarUpdate) -> Car:
        car = db.query(Car).filter(Car.id == car_id, Car.seller_id == seller_id).first()
        if not car:
            raise HTTPException(status_code=404, detail="Car not found or unauthorized")
        
        update_dict = update_data.model_dump(exclude_unset=True)
        
        if "images" in update_dict:
            # Remove existing images
            db.query(AssetImage).filter(AssetImage.car_id == car_id).delete()
            
            # Add new images
            images_data = update_dict.pop("images")
            if images_data:
                for img_data in images_data:
                    img = AssetImage(
                        car_id=car_id,
                        image_url=img_data["image_url"] if isinstance(img_data, dict) else img_data.image_url
                    )
                    db.add(img)

        for key, value in update_dict.items():
            setattr(car, key, value)
            
        db.commit()
        db.refresh(car)
        return car

    def add_units_to_listing(self, db: Session, car_id: UUID, seller_id: UUID, units_data: List[CarUnitCreate]) -> List[CarUnit]:
        car = db.query(Car).filter(Car.id == car_id, Car.seller_id == seller_id).first()
        if not car:
            raise HTTPException(status_code=404, detail="Car listing not found or unauthorized")

        # Check VIN uniqueness
        vins = [u.vin for u in units_data]
        existing = db.query(CarUnit).filter(CarUnit.vin.in_(vins)).first()
        if existing:
            raise HTTPException(status_code=400, detail=f"VIN {existing.vin} already exists")

        new_units = []
        for unit_data in units_data:
            unit = CarUnit(
                car_id=car_id,
                vin=unit_data.vin,
                mileage=unit_data.mileage,
                color=unit_data.color,
                status="available"
            )
            db.add(unit)
            new_units.append(unit)

        # If listing was out of stock, mark it as available again
        if car.status == "out_of_stock":
            car.status = "available"

        db.commit()
        for u in new_units:
            db.refresh(u)
        return new_units

automotive_service = AutomotiveService()
