from sqlalchemy.orm import Session
from uuid import UUID
from datetime import datetime
from decimal import Decimal
from typing import List, Optional, Dict, Any
from fastapi import HTTPException
from sqlalchemy import or_

from core.model import (
    Car, CarUnit, Property, PropertyUnit, Phone, PhoneUnit, 
    GeneralInspection, GeneralAgreement, Payment, AssetImage,
    Profile, User, SellerProfile
)
from core.notifications_service import create_notification
from core.paystack_service import paystack_service
from core.payment_service import payment_service
from schemas.assets import (
    AssetInspectionSchedule, 
    AssetInspectionReview, 
    AssetInspectionComplete,
    AssetAgreementBase,
    AssetMini,
    AgreementPaymentInitialize
)

class AssetService():
    def update_unit_status(self, db: Session, asset_type: str, status: str, unit_id: Optional[UUID] = None, asset_id: Optional[UUID] = None):
        """
        Unified method to update unit or asset status based on inspection/agreement stage.
        Handles CarUnit, PhoneUnit, and PropertyUnit consistently.
        """
        # Mapping from GeneralInspection/GeneralAgreement statuses to physical unit statuses
        unit_status_map = {
            # Shared or mapped statuses
            "scheduled": "pending_inspection",
            "confirmed": "pending_inspection",
            "completed": "inspected",
            "agreement_pending": "inspected",
            "agreement_accepted": "awaiting_payment",
            "pending_deposit": "awaiting_payment",
            "paid": "sold",
            "active": "sold",
            "completed_agreement": "sold"
        }

        # Override for property specific naming
        if asset_type == "property":
            unit_status_map["completed"] = "property_inspected"
            unit_status_map["agreement_pending"] = "property_inspected"
            unit_status_map["active"] = "under_financing" # Properties under financing

        new_status = unit_status_map.get(status)
        if not new_status:
            return

        if asset_type == "automotive" and unit_id:
            unit = db.query(CarUnit).filter(CarUnit.id == unit_id).first()
            if unit:
                # CarUnit doesn't have pending_inspection, skip if that's the status
                if new_status != "pending_inspection":
                    unit.status = new_status
                
                # If sold/awaiting_payment, check if main listing should be out of stock
                if new_status in ["sold", "awaiting_payment"]:
                    available_count = db.query(CarUnit).filter(
                        CarUnit.car_id == unit.car_id,
                        CarUnit.status.in_(["available", "inspected"]),
                        CarUnit.id != unit.id
                    ).count()
                    if available_count == 0:
                        car = db.query(Car).filter(Car.id == unit.car_id).first()
                        if car: car.status = "out_of_stock"

        elif asset_type == "phone" and unit_id:
            unit = db.query(PhoneUnit).filter(PhoneUnit.id == unit_id).first()
            if unit:
                if new_status != "pending_inspection":
                    unit.status = new_status
                
                if new_status in ["sold", "awaiting_payment"]:
                    available_count = db.query(PhoneUnit).filter(
                        PhoneUnit.phone_id == unit.phone_id,
                        PhoneUnit.status.in_(["available", "inspected"]),
                        PhoneUnit.id != unit.id
                    ).count()
                    if available_count == 0:
                        phone = db.query(Phone).filter(Phone.id == unit.phone_id).first()
                        if phone: phone.status = "out_of_stock"

        elif asset_type == "property":
            # If unit_id is provided, update specific unit
            if unit_id:
                unit = db.query(PropertyUnit).filter(PropertyUnit.id == unit_id).first()
                if unit:
                    unit.status = new_status
            
            # If asset_id is provided, update main property status or all units if acquisitions
            if asset_id:
                prop = db.query(Property).filter(Property.id == asset_id).first()
                if prop:
                    # Acquisitions propagate to all units
                    if prop.acquisition_session_id and new_status in ["pending_inspection", "property_inspected"]:
                        db.query(PropertyUnit).filter(PropertyUnit.property_id == asset_id).update({"status": new_status})
                    
                    # If sold/awaiting_payment, check if main listing should update status
                    if new_status in ["sold", "awaiting_payment", "under_financing"]:
                        available_count = db.query(PropertyUnit).filter(
                            PropertyUnit.property_id == asset_id,
                            PropertyUnit.status.in_(["available", "property_inspected", "pending_inspection"]),
                            PropertyUnit.id != unit_id if unit_id else True
                        ).count()
                        
                        if available_count == 0:
                            prop.status = new_status
                    else:
                        # Update main property status for global changes
                        prop.status = new_status

    def _get_asset_details(self, db: Session, asset_type: str, asset_id: UUID) -> AssetMini:
        """Helper to fetch basic asset details for nested response"""
        title = ""
        price = Decimal(0)
        min_deposit = Decimal(10)
        image_url = None
        
        if asset_type == "automotive":
            asset = db.query(Car).filter(Car.id == asset_id).first()
            if asset:
                title = f"{asset.brand} {asset.model}"
                price = asset.price
                min_deposit = asset.min_deposit_percentage
        elif asset_type == "property":
            asset = db.query(Property).filter(Property.id == asset_id).first()
            if asset:
                title = asset.title
                price = asset.price
                min_deposit = asset.min_deposit_percentage
        elif asset_type == "phone":
            asset = db.query(Phone).filter(Phone.id == asset_id).first()
            if asset:
                title = f"{asset.brand} {asset.model}"
                price = asset.price
                min_deposit = asset.min_deposit_percentage
        
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
            
        return AssetMini(id=asset_id, type=asset_type, title=title, price=price, min_deposit_percentage=min_deposit, image_url=image_url)

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
            "priority": "high",
            "channel": ["email", "in_app"]
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

    def list_seller_payments(self, db: Session, seller_id: UUID) -> List[Payment]:
        return db.query(Payment).filter(Payment.seller_id == seller_id, Payment.agreement_id != None).order_by(Payment.created_at.desc()).all()

    def list_user_payments(self, db: Session, user_id: UUID) -> List[Payment]:
        return db.query(Payment).filter(Payment.buyer_id == user_id, Payment.agreement_id != None).order_by(Payment.created_at.desc()).all()

    def get_payment(self, db: Session, user_id: UUID, payment_id: UUID) -> Payment:
        payment = db.query(Payment).filter(
            Payment.id == payment_id,
            or_(
                Payment.buyer_id == user_id,
                Payment.seller_id == user_id
            )
        ).first()
        
        if payment and payment.agreement:
             payment.agreement.asset = self._get_asset_details(db, payment.agreement.asset_type, payment.agreement.asset_id)
             
        return payment

    def complete_inspection(self, db: Session, user_id: UUID, inspection_id: UUID, data: AssetInspectionComplete) -> GeneralInspection:
        inspection = db.query(GeneralInspection).filter(
            GeneralInspection.id == inspection_id, 
            GeneralInspection.user_id == user_id
        ).first()
        
        if not inspection:
            raise HTTPException(status_code=404, detail="Inspection not found")

        # 1. Update Inspection
        inspection.status = "agreement_pending"
        inspection.agreed_price = data.agreed_price
        inspection.notes = data.notes or inspection.notes
        if data.unit_id:
            inspection.unit_id = data.unit_id
        
        # 2. Update physical asset status
        self.update_unit_status(db, inspection.asset_type, "completed", unit_id=inspection.unit_id, asset_id=inspection.asset_id)

        # 3. Create or Update Agreement automatically in pending_review
        existing = db.query(GeneralAgreement).filter(GeneralAgreement.inspection_id == inspection_id).first()
        if not existing:
            new_agreement = GeneralAgreement(
                seller_id=inspection.seller_id,
                user_id=inspection.user_id,
                inspection_id=inspection_id,
                asset_type=inspection.asset_type,
                asset_id=inspection.asset_id,
                unit_id=inspection.unit_id,
                total_price=data.agreed_price,
                deposit_paid=0,
                remaining_balance=data.agreed_price,
                plan_type=data.plan_type,
                duration_months=data.duration_months,
                monthly_installment=data.monthly_installment,
                status="pending_review",
                acquisition_session_id=inspection.acquisition_session_id
            )
            db.add(new_agreement)
        else:
            # Update existing agreement with the selected unit and price
            existing.unit_id = inspection.unit_id
            existing.total_price = data.agreed_price
            existing.remaining_balance = data.agreed_price
            existing.plan_type = data.plan_type
            existing.duration_months = data.duration_months
            existing.monthly_installment = data.monthly_installment

        db.commit()
        db.refresh(inspection)

        # 4. Update session status if linked
        if inspection.acquisition_session_id:
            from core.model import RealEstateSessionRequest
            sess = db.query(RealEstateSessionRequest).filter(RealEstateSessionRequest.id == inspection.acquisition_session_id).first()
            if sess:
                sess.status = "processing"
                db.commit()

        # Notify Seller
        create_notification(db, {
            "user_id": str(inspection.seller_id),
            "type": "inspection_complete",
            "title": "Inspection Completed",
            "message": f"A customer has completed the inspection for your {inspection.asset_type}. An agreement is now pending your review.",
            "priority": "medium",
            "channels": ["in_app", "email"]
        })

        return inspection

    def create_agreement(self, db: Session, user_id: UUID, data: AssetAgreementBase, is_seller: bool = True) -> GeneralAgreement:
        # Get asset to verify details
        asset = None
        if data.asset_type == "automotive":
            asset = db.query(Car).filter(Car.id == data.asset_id).first()
        elif data.asset_type == "property":
            asset = db.query(Property).filter(Property.id == data.asset_id).first()
        elif data.asset_type == "phone":
            asset = db.query(Phone).filter(Phone.id == data.asset_id).first()
        
        if not asset:
            raise HTTPException(status_code=404, detail="Asset not found")

        # Set IDs correctly based on who is calling
        if is_seller:
            if asset.seller_id != user_id:
                raise HTTPException(status_code=403, detail="You do not own this asset")
            seller_id = user_id
            buyer_id = None
            if data.inspection_id:
                inspection = db.query(GeneralInspection).filter(GeneralInspection.id == data.inspection_id).first()
                if inspection:
                    buyer_id = inspection.user_id
            if not buyer_id:
                 raise HTTPException(status_code=400, detail="Buyer ID could not be resolved from inspection")
        else:
            # Customer initiated
            seller_id = asset.seller_id
            buyer_id = user_id

        remaining_balance = data.total_price - (data.deposit_paid or 0)

        new_agreement = GeneralAgreement(
            seller_id=seller_id,
            user_id=buyer_id,
            inspection_id=data.inspection_id,
            asset_type=data.asset_type,
            asset_id=data.asset_id,
            unit_id=data.unit_id,
            total_price=data.total_price,
            deposit_paid=data.deposit_paid or 0,
            remaining_balance=remaining_balance,
            plan_type=data.plan_type,
            duration_months=data.duration_months,
            monthly_installment=data.monthly_installment,
            status="pending_review",  # Start in review
            acquisition_session_id=data.acquisition_session_id if hasattr(data, 'acquisition_session_id') else (inspection.acquisition_session_id if data.inspection_id and inspection else None)
        )
        
        db.add(new_agreement)
        
        # update inspection status if exists
        if data.inspection_id:
            inspection = db.query(GeneralInspection).filter(GeneralInspection.id == data.inspection_id).first()
            if inspection:
                inspection.status = "agreement_pending"

        db.commit()
        db.refresh(new_agreement)

        # Notify Buyer
        create_notification(db, {
            "user_id": str(new_agreement.user_id),
            "type": "agreement_created",
            "title": "Agreement Created",
            "message": f"Your agreement for the {new_agreement.asset_type} has been created and is now pending seller review.",
            "priority": "medium",
            "channels": ["in_app", "email"]
        })

        return new_agreement

    def approve_agreement(self, db: Session, seller_id: UUID, agreement_id: UUID, unit_id: Optional[UUID] = None) -> GeneralAgreement:
        agreement = db.query(GeneralAgreement).filter(
            GeneralAgreement.id == agreement_id,
            GeneralAgreement.seller_id == seller_id
        ).first()

        if not agreement:
            raise HTTPException(status_code=404, detail="Agreement not found or unauthorized")
        
        if agreement.status != "pending_review":
            raise HTTPException(status_code=400, detail="Agreement is not in pending_review status")

        # Update unit_id if provided by seller at approval time
        if unit_id:
            agreement.unit_id = unit_id
            if agreement.inspection_id:
                inspection = db.query(GeneralInspection).filter(GeneralInspection.id == agreement.inspection_id).first()
                if inspection:
                    inspection.unit_id = unit_id

        # Update Agreement status
        agreement.status = "pending_deposit"
        
        # Update Inspection status
        if agreement.inspection_id:
            inspection = db.query(GeneralInspection).filter(GeneralInspection.id == agreement.inspection_id).first()
            if inspection:
                inspection.status = "agreement_accepted"

        # Update asset unit status
        self.update_unit_status(db, agreement.asset_type, "awaiting_payment", unit_id=agreement.unit_id, asset_id=agreement.asset_id)

        db.commit()
        db.refresh(agreement)

        # Notify Buyer
        create_notification(db, {
            "user_id": str(agreement.user_id),
            "type": "agreement_approved",
            "title": "Agreement Approved!",
            "message": f"Your agreement for the {agreement.asset_type} has been approved by the seller. Please proceed to pay your deposit to activate it.",
            "priority": "high",
            "channels": ["in_app", "email"]
        })

        return agreement

    def delete_inspection(self, db: Session, user_id: UUID, inspection_id: UUID) -> bool:
        inspection = db.query(GeneralInspection).filter(
            GeneralInspection.id == inspection_id,
            or_(GeneralInspection.user_id == user_id, GeneralInspection.seller_id == user_id)
        ).first()
        
        if not inspection:
            raise HTTPException(status_code=404, detail="Inspection not found or unauthorized")
        
        db.delete(inspection)
        db.commit()
        return True
    def reject_agreement(self, db: Session, seller_id: UUID, agreement_id: UUID) -> GeneralAgreement:
        agreement = db.query(GeneralAgreement).filter(
            GeneralAgreement.id == agreement_id,
            GeneralAgreement.seller_id == seller_id
        ).first()

        if not agreement:
            raise HTTPException(status_code=404, detail="Agreement not found or unauthorized")
        
        if agreement.status != "pending_review":
            raise HTTPException(status_code=400, detail="Agreement is not in pending_review status")

        # Update Agreement status - Using 'cancelled' as 'rejected' is not in the Enum yet
        agreement.status = "cancelled"
        
        # Reset Inspection status so customer can try again
        if agreement.inspection_id:
            inspection = db.query(GeneralInspection).filter(GeneralInspection.id == agreement.inspection_id).first()
            if inspection:
                inspection.status = "confirmed"

        db.commit()
        db.refresh(agreement)

        # Notify Buyer
        create_notification(db, {
            "user_id": str(agreement.user_id),
            "type": "agreement_rejected",
            "title": "Agreement Declined",
            "message": f"The seller has declined the agreement terms for the {agreement.asset_type}. You can try scheduling another inspection to renegotiate.",
            "priority": "high",
            "channels": ["in_app", "email"]
        })

        return agreement

    def initialize_agreement_payment(self, db: Session, user_id: UUID, agreement_id: UUID, data: AgreementPaymentInitialize) -> Dict[str, Any]:
        agreement = db.query(GeneralAgreement).filter(
            GeneralAgreement.id == agreement_id,
            GeneralAgreement.user_id == user_id
        ).first()

        if not agreement:
            raise HTTPException(status_code=404, detail="Agreement not found")
        
        # Check if it's the first payment (deposit) - simplified check
        is_deposit = (agreement.deposit_paid or 0) == 0
        payment_type = "deposit" if is_deposit else "installment"

        # Check for minimum deposit if it's a deposit payment
        if is_deposit:
            # Get asset min deposit info
            asset = self._get_asset_details(db, agreement.asset_type, agreement.asset_id)
            min_percent = asset.min_deposit_percentage if asset else 10
            min_amount = agreement.total_price * (Decimal(str(min_percent)) / 100)
            
            if data.amount < min_amount:
                raise HTTPException(
                    status_code=400, 
                    detail=f"Initial deposit must be at least {min_percent}% (₦{min_amount:,.2f})"
                )
        
        # Use unified PaymentService for initialization
        category = "asset_deposit" if payment_type == "deposit" else "asset_installment"
        
        return payment_service.initialize_payment(
            db=db,
            user_id=str(user_id),
            email=data.email,
            amount_kobo=int(data.amount * 100),
            category=category,
            agreement_id=str(agreement_id),
            metadata={"payment_type": payment_type}
        )

    def verify_agreement_payment(self, db: Session, reference: str) -> Dict[str, Any]:
        """Verify an agreement payment using the unified payment service"""
        return payment_service.verify_transaction(db, reference)

asset_service = AssetService()
