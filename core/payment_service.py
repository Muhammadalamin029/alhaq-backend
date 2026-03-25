from sqlalchemy.orm import Session
from sqlalchemy import func
from typing import Optional, Dict, Any, List
from decimal import Decimal
import uuid
import logging
from datetime import datetime
from fastapi import HTTPException, status

from core.model import (
    Payment, Order, GeneralAgreement, Profile, SellerProfile, 
    GeneralInspection, CarUnit, PhoneUnit, Property, PropertyUnit, 
    RealEstateSessionRequest
)
from core.paystack_service import paystack_service
from core.notifications_service import create_notification
from core.seller_payout_service import seller_payout_service

logger = logging.getLogger(__name__)

class PaymentService:
    def __init__(self):
        self.paystack = paystack_service

    def initialize_payment(
        self, 
        db: Session, 
        user_id: str, 
        email: str, 
        amount_kobo: int, 
        category: str,
        order_id: Optional[str] = None,
        agreement_id: Optional[str] = None,
        callback_url: Optional[str] = None,
        metadata: Optional[Dict] = None
    ) -> Dict[str, Any]:
        """Unified payment initialization for Orders and Asset Agreements"""
        
        # 1. Validation based on category
        if category == "order" and not order_id:
            raise HTTPException(status_code=400, detail="order_id is required for order payments")
        if category in ["asset_deposit", "asset_installment"] and not agreement_id:
            raise HTTPException(status_code=400, detail="agreement_id is required for asset payments")

        # 2. Check if we have an existing pending payment and reuse it
        existing_payment = db.query(Payment).filter(
            Payment.buyer_id == user_id,
            Payment.status == "pending",
            Payment.payment_category == category
        )
        if order_id: existing_payment = existing_payment.filter(Payment.order_id == order_id)
        if agreement_id: existing_payment = existing_payment.filter(Payment.agreement_id == agreement_id)
        
        existing_payment = existing_payment.first()

        # 4. Infer payment_type if missing in metadata
        payment_type = (metadata or {}).get("payment_type")
        if not payment_type:
            if category == "asset_deposit": payment_type = "deposit"
            elif category == "asset_installment": payment_type = "installment"
            elif category == "order": payment_type = "order"
            elif category == "full_pay": payment_type = "full_pay"

        # Get seller_id if applicable
        seller_id = None
        if agreement_id:
            agreement = db.query(GeneralAgreement).filter(GeneralAgreement.id == agreement_id).first()
            if agreement:
                seller_id = agreement.seller_id
        elif order_id:
            # For orders, we might have multiple sellers, so seller_id at the payment level might be None 
            # and handled per item or per split. But for simplicity if it's single seller we can set it.
            pass
        
        if existing_payment:
            # Re-initialize with Paystack if it's old or just return existing
            logger.info(f"Re-using existing pending payment for {category}: {existing_payment.id}")
            # We update the amount in case it changed
            existing_payment.amount = Decimal(amount_kobo) / 100
            
        # 3. Generate unique reference
        reference = f"DEMIGHT_{uuid.uuid4().hex[:10].upper()}"
        
        # 4. Prepare metadata for Paystack
        ps_metadata = {
            "user_id": str(user_id),
            "category": category,
            "order_id": str(order_id) if order_id else None,
            "agreement_id": str(agreement_id) if agreement_id else None,
            **(metadata or {})
        }

        # 5. Initialize Paystack
        ps_res = self.paystack.initialize_transaction(
            email=email,
            amount=amount_kobo,
            reference=reference,
            metadata=ps_metadata,
            callback_url=callback_url
        )

        if not ps_res.get("status"):
            raise HTTPException(status_code=400, detail="Paystack initialization failed")

        # 6. Save or Update record
        if existing_payment:
            payment = existing_payment
            payment.transaction_id = reference
            payment.reference = reference
            payment.authorization_url = ps_res["data"]["authorization_url"]
            payment.access_code = ps_res["data"]["access_code"]
        else:
            payment = Payment(
                order_id=order_id,
                agreement_id=agreement_id,
                buyer_id=user_id,
                seller_id=seller_id,
                amount=Decimal(amount_kobo) / 100,
                status="pending",
                payment_category=category,
                payment_type=payment_type,
                transaction_id=reference,
                reference=reference,
                authorization_url=ps_res["data"]["authorization_url"],
                access_code=ps_res["data"]["access_code"]
            )
            db.add(payment)
        
        # 7. Specific link logic
        if category == "order":
            order = db.query(Order).filter(Order.id == order_id).first()
            if order:
                order.payment_url = ps_res["data"]["authorization_url"]
                order.payment_reference = reference
                order.status = "processing"

        db.commit()
        return ps_res["data"]

    def verify_transaction(self, db: Session, reference: str) -> Dict[str, Any]:
        """Unified verification logic"""
        ps_res = self.paystack.verify_transaction(reference)
        
        if not ps_res.get("status"):
            return ps_res

        data = ps_res.get("data", {})
        status_raw = data.get("status")

        payment = db.query(Payment).filter(Payment.transaction_id == reference).first()
        if not payment:
            return ps_res

        if status_raw == "success":
            if payment.status != "completed":
                self._handle_completion(db, payment)
        elif status_raw in ["failed", "abandoned", "reversed"]:
            payment.status = "failed"
            db.commit()
        
        return ps_res

    def _handle_completion(self, db: Session, payment: Payment):
        """Processes logic after successful payment confirmation"""
        logger.info(f"Completing payment {payment.id} (Category: {payment.payment_category}, Amount: {payment.amount})")
        payment.status = "completed"
        category = payment.payment_category
        
        # 1. Handle Order Logic
        if hasattr(payment, 'order_id') and payment.order_id:
            order = db.query(Order).filter(Order.id == payment.order_id).first()
            if order:
                order.status = "paid"
                # Update seller balances
                seller_payout_service.update_seller_balance(db, str(payment.seller_id), str(payment.order_id), "paid", "processing")
                
                create_notification(db, {
                    "user_id": str(payment.buyer_id),
                    "type": "payment_successful",
                    "title": "Order Payment Confirmed",
                    "message": f"Your payment of ₦{payment.amount:,.2f} for Order #{str(order.id)[:8]} has been confirmed.",
                    "priority": "high"
                })

        # 3. Handle Asset Agreement Logic
        if hasattr(payment, 'agreement_id') and payment.agreement_id:
            logger.info(f"Processing agreement payment for agreement_id: {payment.agreement_id}")
            agreement = db.query(GeneralAgreement).filter(GeneralAgreement.id == payment.agreement_id).first()
            if agreement:
                logger.info(f"Loaded agreement status: {agreement.status}, Asset Type: {agreement.asset_type}")
                if (payment.payment_type or payment.payment_category) in ["deposit", "asset_deposit"]:
                    agreement.deposit_paid = (agreement.deposit_paid or 0) + payment.amount
                    agreement.remaining_balance = (agreement.remaining_balance or agreement.total_price) - payment.amount
                    
                    # If this "deposit" actually paid the full price
                    if agreement.remaining_balance <= 0:
                        agreement.status = "completed"
                        agreement.remaining_balance = 0
                        logger.info(f"Agreement {agreement.id} fully paid via deposit")
                    else:
                        agreement.status = "active"

                    if agreement.inspection_id:
                        inspection = db.query(GeneralInspection).filter(GeneralInspection.id == agreement.inspection_id).first()
                        if inspection: inspection.status = "agreement_accepted"

                    # Update unit/asset status to final held state
                    logger.info("Updating asset status for initial deposit/payment")
                    if agreement.asset_type == "property":
                        prop = db.query(Property).filter(Property.id == agreement.asset_id).first()
                        if prop: 
                            if agreement.status == "completed":
                                if agreement.acquisition_session_id:
                                    prop.status = "acquired"
                                else:
                                    prop.status = "rented" if prop.listing_type == "rental" else "sold"
                            else:
                                prop.status = "under_financing"
                            logger.info(f"Property {prop.id} status updated to {prop.status}")
                        
                        # Also update specific unit if this is a single unit purchase
                        if agreement.unit_id:
                            unit = db.query(PropertyUnit).filter(PropertyUnit.id == agreement.unit_id).first()
                            if unit: 
                                if agreement.status == "completed":
                                    unit.status = "rented" if prop and prop.listing_type == "rental" else "sold"
                                else:
                                    unit.status = "under_financing"
                                logger.info(f"Property Unit {unit.id} status updated to {unit.status}")
                    elif agreement.unit_id:
                        if agreement.asset_type == "automotive":
                            unit = db.query(CarUnit).filter(CarUnit.id == agreement.unit_id).first()
                            if unit: unit.status = "sold"
                        elif agreement.asset_type == "phone":
                            unit = db.query(PhoneUnit).filter(PhoneUnit.id == agreement.unit_id).first()
                            if unit: unit.status = "sold"
                else:
                    agreement.remaining_balance = (agreement.remaining_balance or 0) - payment.amount
                    if agreement.remaining_balance <= 0:
                        agreement.status = "completed"

                # Update Seller Balance for Assets
                seller = db.query(SellerProfile).filter(SellerProfile.id == agreement.seller_id).first()
                if seller:
                    seller.pending_balance = (seller.pending_balance or 0) + payment.amount
                    seller.total_revenue = (seller.total_revenue or 0) + payment.amount
                    
                    # If agreement is completed, move the total paid from pending to available
                    if agreement.status == "completed":
                        seller.pending_balance -= agreement.total_price
                        seller.available_balance = (seller.available_balance or 0) + agreement.total_price
                    else:
                        # Update next_due_date to 1 month from now for installments
                        from datetime import timedelta
                        agreement.next_due_date = datetime.utcnow() + timedelta(days=30)

                # Send primary payment confirmation
                create_notification(db, {
                    "user_id": str(payment.buyer_id),
                    "type": "payment_successful",
                    "title": "Agreement Payment Confirmed",
                    "message": f"Your payment of ₦{payment.amount:,.2f} for your {agreement.asset_type} agreement has been confirmed. Next payment due on {agreement.next_due_date.strftime('%B %d, %Y') if agreement.next_due_date else 'N/A'}.",
                    "priority": "high"
                })

                # Ownership logic for acquisitions
                if agreement.acquisition_session_id:
                    session_req = db.query(RealEstateSessionRequest).filter(RealEstateSessionRequest.id == agreement.acquisition_session_id).first()
                    if session_req:
                        if agreement.status == "completed":
                            session_req.status = "acquired"
                            # Also update the asset status to 'acquired'
                            if agreement.asset_type == "property":
                                prop = db.query(Property).filter(Property.id == agreement.asset_id).first()
                                if prop: 
                                    prop.status = "acquired"
                                    # Update all units to acquired
                                    for unit in (prop.units or []):
                                        unit.status = "acquired"
                            elif agreement.asset_type == "automotive" and agreement.unit_id:
                                unit = db.query(CarUnit).filter(CarUnit.id == agreement.unit_id).first()
                                if unit: unit.status = "sold" # Or other appropriate status
                            elif agreement.asset_type == "phone" and agreement.unit_id:
                                from core.model import PhoneUnit
                                unit = db.query(PhoneUnit).filter(PhoneUnit.id == agreement.unit_id).first()
                                if unit: unit.status = "sold"
                        elif agreement.status == "active":
                            session_req.status = "processing"
                else:
                    # Individual Customer Purchase (Not platform acquisition)
                    if agreement.status == "completed" and agreement.asset_type == "property" and agreement.unit_id:
                        unit = db.query(PropertyUnit).filter(PropertyUnit.id == agreement.unit_id).first()
                        if unit:
                            # Set to sold or rented based on parent property listing_type
                            parent = db.query(Property).filter(Property.id == agreement.asset_id).first()
                            if parent and parent.listing_type == "rental":
                                unit.status = "rented"
                            else:
                                unit.status = "sold"
                            # If all units are sold, mark property as sold? 
                            # (Optional logic but maybe good for UX)

                # Special "Ownership" notification if agreement is now fully paid
                if agreement.status == "completed":
                    asset_noun = "Property" if agreement.asset_type == "property" else ("Car" if agreement.asset_type == "automotive" else "Phone")
                    create_notification(db, {
                        "user_id": str(payment.buyer_id),
                        "type": "agreement_completed",
                        "title": f"🎉 Congratulations! You now own this {asset_noun}!",
                        "message": f"Your {agreement.asset_type} agreement has been fully paid. You are now the full owner of this asset. Thank you for choosing Demight Tech!",
                        "priority": "urgent",
                        "channels": ["in_app", "email"]
                    })

        db.commit()

payment_service = PaymentService()
