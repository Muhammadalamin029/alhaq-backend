from sqlalchemy.orm import Session
from sqlalchemy import or_
from uuid import UUID
from datetime import datetime
from typing import List, Optional, Dict, Any
from fastapi import HTTPException, status

from core.model import Car, CarUnit, CarInspection, User, SellerProfile, CarAgreement, CarPayment
from schemas.automotive import CarCreate, CarUpdate, CarInspectionSchedule, CarUnitCreate
from core.notifications_service import create_notification
from decimal import Decimal

class AutomotiveService:
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

        db.commit()
        db.refresh(car_listing)
        return car_listing

    def schedule_inspection(self, db: Session, user_id: UUID, car_id: UUID, inspection_date: datetime, unit_id: UUID = None) -> CarInspection:
        car = db.query(Car).filter(Car.id == car_id).first()
        if not car:
            raise HTTPException(status_code=404, detail="Car listing not found")
        
        # If no specific unit, pick an available one
        if not unit_id:
            available_unit = db.query(CarUnit).filter(CarUnit.car_id == car_id, CarUnit.status == "available").first()
            if not available_unit:
                raise HTTPException(status_code=400, detail="No available units for this car at the moment")
            unit_id = available_unit.id

        inspection = CarInspection(
            car_id=car_id,
            unit_id=unit_id,
            user_id=user_id,
            inspection_date=inspection_date,
            status="scheduled"
        )
        
        db.add(inspection)
        db.commit()
        db.refresh(inspection)

        create_notification(db, {
            "user_id": str(car.seller_id),
            "type": "inspection_scheduled",
            "title": "New Inspection Request",
            "message": f"A customer has scheduled an inspection for your {car.brand} {car.model}.",
            "priority": "medium",
            "channels": ["in_app"]
        })
        return inspection

    def seller_action_on_inspection(self, db: Session, seller_id: UUID, inspection_id: UUID, action: str) -> CarInspection:
        inspection = db.query(CarInspection).join(Car).filter(
            CarInspection.id == inspection_id,
            Car.seller_id == seller_id
        ).first()
        
        if not inspection:
            raise HTTPException(status_code=404, detail="Inspection not found")

        unit = db.query(CarUnit).filter(CarUnit.id == inspection.unit_id).first()
        car = inspection.car

        if action == "accept":
            inspection.status = "agreement_accepted"
            
            # Create Agreement for the SPECIFIC UNIT
            agreement = CarAgreement(
                user_id=inspection.user_id,
                car_id=car.id,
                unit_id=unit.id,
                inspection_id=inspection.id,
                total_price=inspection.agreed_price,
                deposit_paid=0,
                remaining_balance=inspection.agreed_price,
                plan_type="flexible",
                status="pending_deposit"
            )
            db.add(agreement)
            
            # Lock ONLY this unit
            if unit:
                unit.status = "awaiting_payment"
                
            # Check if listing as a whole is out of stock
            remaining_stock = db.query(CarUnit).filter(
                CarUnit.car_id == car.id, 
                CarUnit.status == "available"
            ).count()
            
            if remaining_stock == 0:
                car.status = "out_of_stock"

            create_notification(db, {
                "user_id": str(inspection.user_id),
                "type": "car_approved",
                "title": "Offer Accepted!",
                "message": f"The seller has accepted your offer for the {car.brand} {car.model}. Agreement created for VIN {unit.vin}.",
                "priority": "high",
                "channels": ["in_app", "email"]
            })
        else:
            inspection.status = "rejected"
            if unit:
                unit.status = "available"
                # If listing was out of stock, restore it
                if car.status == "out_of_stock":
                    car.status = "available"

        db.commit()
        db.refresh(inspection)
        return inspection

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
        for key, value in update_dict.items():
            setattr(car, key, value)
            
        db.commit()
        db.refresh(car)
        return car

    def complete_inspection(self, db: Session, user_id: UUID, inspection_id: UUID, notes: str, agreed_price: Decimal) -> CarInspection:
        inspection = db.query(CarInspection).filter(CarInspection.id == inspection_id, CarInspection.user_id == user_id).first()
        if not inspection:
            raise HTTPException(status_code=404, detail="Inspection request not found")

        if inspection.status != "scheduled":
            raise HTTPException(status_code=400, detail="Only scheduled inspections can be completed")

        inspection.notes = notes
        inspection.agreed_price = agreed_price
        inspection.status = "agreement_pending"
        
        # Mark the specific unit as inspected
        unit = db.query(CarUnit).filter(CarUnit.id == inspection.unit_id).first()
        if unit:
            unit.status = "inspected"

        db.commit()
        db.refresh(inspection)

        create_notification(db, {
            "user_id": str(inspection.car.seller_id),
            "type": "agreement_completed",
            "title": "Offer Made",
            "message": f"Customer offered ₦{agreed_price:,.2f} for {inspection.car.brand}. Please review.",
            "priority": "high",
            "channels": ["in_app", "email"]
        })
        return inspection

    def record_car_payment(self, db: Session, agreement_id: UUID, user_id: UUID, amount: Decimal, paystack_ref: str, payment_type: str) -> CarPayment:
        agreement = db.query(CarAgreement).filter(CarAgreement.id == agreement_id, CarAgreement.user_id == user_id).first()
        if not agreement:
            raise HTTPException(status_code=404, detail="Agreement not found")
            
        payment = CarPayment(
            agreement_id=agreement_id,
           user_id=user_id,
            amount=amount,
            paystack_ref=paystack_ref,
            payment_type=payment_type,
            status="success"
        )
        
        agreement.remaining_balance -= amount
        if agreement.remaining_balance <= 0:
            agreement.status = "completed"
            # Update physical unit status to sold
            unit = db.query(CarUnit).filter(CarUnit.id == agreement.unit_id).first()
            if unit:
                unit.status = "sold"

        db.add(payment)
        db.commit()
        db.refresh(payment)
        return payment

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

    def list_seller_inspections(self, db: Session, seller_id: UUID) -> List[CarInspection]:
        return db.query(CarInspection).join(Car).filter(Car.seller_id == seller_id).order_by(CarInspection.created_at.desc()).all()

    def list_user_inspections(self, db: Session, user_id: UUID) -> List[CarInspection]:
        return db.query(CarInspection).filter(CarInspection.user_id == user_id).order_by(CarInspection.created_at.desc()).all()

    def list_seller_agreements(self, db: Session, seller_id: UUID) -> List[CarAgreement]:
        return db.query(CarAgreement).join(Car).filter(Car.seller_id == seller_id).order_by(CarAgreement.created_at.desc()).all()

    def list_user_agreements(self, db: Session, user_id: UUID) -> List[CarAgreement]:
        # CarAgreement.user_id references Profile.id which is same as User.id
        return db.query(CarAgreement).filter(CarAgreement.user_id == user_id).order_by(CarAgreement.created_at.desc()).all()

    def get_agreement(self, db: Session, agreement_id: UUID, user_id: UUID = None) -> Optional[CarAgreement]:
        query = db.query(CarAgreement).filter(CarAgreement.id == agreement_id)
        if user_id:
            # Can be either customer or seller
            query = query.join(Car).filter(or_(CarAgreement.user_id == user_id, Car.seller_id == user_id))
        return query.first()

    def update_agreement(self, db: Session, agreement_id: UUID, seller_id: UUID, update_data: Dict[str, Any]) -> CarAgreement:
        agreement = db.query(CarAgreement).join(Car).filter(
            CarAgreement.id == agreement_id,
            Car.seller_id == seller_id
        ).first()
        
        if not agreement:
            raise HTTPException(status_code=404, detail="Agreement not found or unauthorized")
        
        for key, value in update_data.items():
            if value is not None:
                setattr(agreement, key, value)
        
        db.commit()
        db.refresh(agreement)
        return agreement

    def list_payments(self, db: Session, user_id: UUID) -> List[CarPayment]:
        return db.query(CarPayment).filter(CarPayment.user_id == user_id).order_by(CarPayment.created_at.desc()).all()

automotive_service = AutomotiveService()
