from sqlalchemy.orm import Session
from uuid import UUID
from datetime import datetime
from decimal import Decimal
from typing import List, Optional, Dict, Any
from fastapi import HTTPException
from sqlalchemy import or_

from core.model import (
    GeneralInspection, 
    GeneralAgreement, 
    GeneralPayment,
    Car, 
    Property, 
    Phone,
    CarUnit,
    PhoneUnit,
    AssetImage
)
from schemas.assets import (
    AssetInspectionSchedule, 
    AssetInspectionReview, 
    AssetInspectionComplete,
    AssetAgreementBase,
    AssetMini
)
from core.notifications_service import create_notification

class AssetService:
    def _get_asset_details(self, db: Session, asset_type: str, asset_id: UUID) -> AssetMini:
        """Helper to fetch basic asset details for nested response"""
        title = ""
        price = Decimal(0)
        image_url = None
        
        if asset_type == "automotive":
            asset = db.query(Car).filter(Car.id == asset_id).first()
            if asset:
                title = f"{asset.brand} {asset.model}"
                price = asset.price
        elif asset_type == "property":
            asset = db.query(Property).filter(Property.id == asset_id).first()
            if asset:
                title = asset.title
                price = asset.price
        elif asset_type == "phone":
            asset = db.query(Phone).filter(Phone.id == asset_id).first()
            if asset:
                title = f"{asset.brand} {asset.model}"
                price = asset.price
        
        # Get first image
        img = db.query(AssetImage).filter(
            or_(
                AssetImage.car_id == asset_id,
                AssetImage.property_id == asset_id,
                AssetImage.phone_id == asset_id,
                AssetImage.product_id == asset_id
            )
        ).first()
        if img:
            image_url = img.image_url
            
        return AssetMini(id=asset_id, type=asset_type, title=title, price=price, image_url=image_url)

    def schedule_inspection(self, db: Session, user_id: UUID, data: AssetInspectionSchedule) -> GeneralInspection:
        # Get seller_id from asset
        seller_id = None
        if data.asset_type == "automotive":
            asset = db.query(Car).filter(Car.id == data.asset_id).first()
        elif data.asset_type == "property":
            asset = db.query(Property).filter(Property.id == data.asset_id).first()
        elif data.asset_type == "phone":
            asset = db.query(Phone).filter(Phone.id == data.asset_id).first()
        
        if not asset:
            raise HTTPException(status_code=404, detail="Asset not found")
        
        seller_id = asset.seller_id

        new_inspection = GeneralInspection(
            seller_id=seller_id,
            user_id=user_id,
            asset_type=data.asset_type,
            asset_id=data.asset_id,
            unit_id=data.unit_id,
            inspection_date=data.inspection_date,
            status="scheduled"
        )
        db.add(new_inspection)
        db.commit()
        db.refresh(new_inspection)

        # Notify Seller
        create_notification(db, {
            "user_id": str(seller_id),
            "type": "inspection_scheduled",
            "title": "New Inspection Request",
            "message": f"A customer wants to inspect your {data.asset_type} listing.",
            "priority": "low",
            "channel": ["in_app", "email"]
        })

        return new_inspection

    def review_inspection(self, db: Session, seller_id: UUID, inspection_id: UUID, data: AssetInspectionReview) -> GeneralInspection:
        inspection = db.query(GeneralInspection).filter(
            GeneralInspection.id == inspection_id, 
            GeneralInspection.seller_id == seller_id
        ).first()
        
        if not inspection:
            raise HTTPException(status_code=404, detail="Inspection not found")

        old_date = inspection.inspection_date
        date_changed = False

        if data.action == "reject":
            inspection.status = "rejected"
            title = "Inspection Rejected"
            message = f"The seller has declined your inspection request for the {inspection.asset_type}."
        else:
            inspection.status = "confirmed"
            if data.inspection_date:
                # Basic check for date string or datetime
                new_date = data.inspection_date if isinstance(data.inspection_date, datetime) else datetime.fromisoformat(data.inspection_date.replace('Z', '+00:00'))
                if old_date.replace(tzinfo=None) != new_date.replace(tzinfo=None):
                    inspection.inspection_date = new_date
                    date_changed = True
            
            title = "Inspection Confirmed"
            if date_changed:
                message = f"The seller has confirmed your inspection but changed the date to {inspection.inspection_date.strftime('%B %d, %Y at %I:%M %p')}. Please check if this works for you."
            else:
                message = f"The seller has confirmed your inspection request for {inspection.inspection_date.strftime('%B %d, %Y at %I:%M %p')}."
        
        db.commit()
        db.refresh(inspection)

        # Notify User
        create_notification(db, {
            "user_id": str(inspection.user_id),
            "type": "inspection_confirmed" if data.action == "approve" else "inspection_rejected",
            "title": title,
            "message": message,
            "priority": "high"
        })

        return inspection

    def list_seller_inspections(self, db: Session, seller_id: UUID) -> List[GeneralInspection]:
        inspections = db.query(GeneralInspection).filter(GeneralInspection.seller_id == seller_id).order_by(GeneralInspection.created_at.desc()).all()
        for ins in inspections:
            ins.asset = self._get_asset_details(db, ins.asset_type, ins.asset_id)
        return inspections

    def list_user_inspections(self, db: Session, user_id: UUID) -> List[GeneralInspection]:
        inspections = db.query(GeneralInspection).filter(GeneralInspection.user_id == user_id).order_by(GeneralInspection.created_at.desc()).all()
        for ins in inspections:
            ins.asset = self._get_asset_details(db, ins.asset_type, ins.asset_id)
        return inspections

    def get_inspection(self, db: Session, user_id: UUID, inspection_id: UUID) -> Optional[GeneralInspection]:
        inspection = db.query(GeneralInspection).filter(
            GeneralInspection.id == inspection_id,
            or_(GeneralInspection.user_id == user_id, GeneralInspection.seller_id == user_id)
        ).first()
        if inspection:
            inspection.asset = self._get_asset_details(db, inspection.asset_type, inspection.asset_id)
        return inspection

    def list_seller_agreements(self, db: Session, seller_id: UUID) -> List[GeneralAgreement]:
        agreements = db.query(GeneralAgreement).filter(GeneralAgreement.seller_id == seller_id).order_by(GeneralAgreement.created_at.desc()).all()
        for ag in agreements:
            ag.asset = self._get_asset_details(db, ag.asset_type, ag.asset_id)
        return agreements

    def list_user_agreements(self, db: Session, user_id: UUID) -> List[GeneralAgreement]:
        agreements = db.query(GeneralAgreement).filter(GeneralAgreement.user_id == user_id).order_by(GeneralAgreement.created_at.desc()).all()
        for ag in agreements:
            ag.asset = self._get_asset_details(db, ag.asset_type, ag.asset_id)
        return agreements

    def get_agreement(self, db: Session, user_id: UUID, agreement_id: UUID) -> Optional[GeneralAgreement]:
        agreement = db.query(GeneralAgreement).filter(
            GeneralAgreement.id == agreement_id,
            or_(GeneralAgreement.user_id == user_id, GeneralAgreement.seller_id == user_id)
        ).first()
        if agreement:
            agreement.asset = self._get_asset_details(db, agreement.asset_type, agreement.asset_id)
        return agreement

    def list_seller_payments(self, db: Session, seller_id: UUID) -> List[GeneralPayment]:
        return db.query(GeneralPayment).join(GeneralAgreement).filter(GeneralAgreement.seller_id == seller_id).order_by(GeneralPayment.created_at.desc()).all()

    def list_user_payments(self, db: Session, user_id: UUID) -> List[GeneralPayment]:
        return db.query(GeneralPayment).filter(GeneralPayment.user_id == user_id).order_by(GeneralPayment.created_at.desc()).all()

    def complete_inspection(self, db: Session, user_id: UUID, inspection_id: UUID, data: AssetInspectionComplete) -> GeneralInspection:
        inspection = db.query(GeneralInspection).filter(
            GeneralInspection.id == inspection_id, 
            or_(GeneralInspection.user_id == user_id, GeneralInspection.seller_id == user_id)
        ).first()
        
        if not inspection:
            raise HTTPException(status_code=404, detail="Inspection not found")

        inspection.status = "agreement_pending"
        inspection.agreed_price = data.agreed_price
        inspection.notes = data.notes or inspection.notes
        
        db.commit()
        db.refresh(inspection)

        # Notify User of price offer
        create_notification(db, {
            "user_id": str(inspection.user_id),
            "type": "inspection_completed",
            "title": "New Price Offer",
            "message": f"An inspection was completed and the seller proposed ₦{data.agreed_price:,.2f}.",
            "priority": "high"
        })

        return inspection

    def create_agreement(self, db: Session, seller_id: UUID, data: AssetAgreementBase) -> GeneralAgreement:
        # Check if asset exists and seller owns it
        if data.asset_type == "automotive":
            asset = db.query(Car).filter(Car.id == data.asset_id, Car.seller_id == seller_id).first()
        elif data.asset_type == "property":
            asset = db.query(Property).filter(Property.id == data.asset_id, Property.seller_id == seller_id).first()
        elif data.asset_type == "phone":
            asset = db.query(Phone).filter(Phone.id == data.asset_id, Phone.seller_id == seller_id).first()
        
        if not asset:
            raise HTTPException(status_code=404, detail="Asset not found or unauthorized")

        # Resolve user_id from inspection if provided
        user_id = None
        if data.inspection_id:
            inspection = db.query(GeneralInspection).filter(GeneralInspection.id == data.inspection_id).first()
            if inspection:
                user_id = inspection.user_id
        
        if not user_id:
            # Fallback (should ideally be passed or resolved)
            raise HTTPException(status_code=400, detail="User ID could not be resolved")

        new_agreement = GeneralAgreement(
            seller_id=seller_id,
            user_id=user_id,
            inspection_id=data.inspection_id,
            asset_type=data.asset_type,
            asset_id=data.asset_id,
            unit_id=data.unit_id,
            total_price=data.total_price,
            deposit_paid=data.deposit_paid or 0,
            remaining_balance=data.total_price - (data.deposit_paid or 0),
            plan_type=data.plan_type,
            duration_months=data.duration_months,
            monthly_installment=data.monthly_installment,
            status="pending_deposit"
        )
        
        db.add(new_agreement)
        
        # update inspection status if exists
        if data.inspection_id:
            inspection = db.query(GeneralInspection).filter(GeneralInspection.id == data.inspection_id).first()
            if inspection:
                inspection.status = "agreement_accepted"

        db.commit()
        db.refresh(new_agreement)
        return new_agreement

asset_service = AssetService()
