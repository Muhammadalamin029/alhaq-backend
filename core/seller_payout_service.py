from sqlalchemy.orm import Session
from sqlalchemy import desc
from typing import List, Dict, Any, Tuple
from decimal import Decimal
from datetime import datetime
import logging
import uuid

from core.model import SellerProfile, SellerPayout, OrderItem, Product
from core.paystack_service import paystack_service
from core.notifications_service import create_notification
from core.system_settings_service import system_settings_service
from core.tasks import send_payout_completed_email, send_payout_failed_email

logger = logging.getLogger(__name__)

class SellerPayoutService:
    """Service for managing seller payouts and earnings"""
    
    # Platform commission rate (5%)
    PLATFORM_FEE_RATE = Decimal('0.05')
    
    def __init__(self):
        self.paystack_service = paystack_service

    def get_platform_fee_rate(self, db: Session) -> Decimal:
        payment_settings = system_settings_service.get_payment_setting_values(db)
        return Decimal(str(payment_settings["commission_rate_percent"])) / Decimal("100")

    def get_minimum_payout_amount(self, db: Session) -> Decimal:
        payment_settings = system_settings_service.get_payment_setting_values(db)
        return Decimal(str(payment_settings["minimum_payout_amount"]))
    
    def calculate_seller_earnings(self, db: Session, seller_id: str, order_id: str) -> Dict[str, Any]:
        """
        Calculate seller earnings from a specific order
        
        Returns:
            Dict with earnings breakdown
        """
        # Get order items for this seller
        order_items = (
            db.query(OrderItem)
            .join(Product)
            .filter(
                Product.seller_id == seller_id,
                OrderItem.order_id == order_id
            )
            .all()
        )
        
        if not order_items:
            return {
                "gross_amount": Decimal('0'),
                "platform_fee": Decimal('0'),
                "net_amount": Decimal('0'),
                "item_count": 0
            }
        
        # Calculate gross amount (total from order items)
        gross_amount = sum(item.quantity * item.price for item in order_items)
        
        # Calculate platform fee using the configured system setting
        platform_fee = gross_amount * self.get_platform_fee_rate(db)
        
        # Calculate net amount (what seller receives)
        net_amount = gross_amount - platform_fee
        
        return {
            "gross_amount": gross_amount,
            "platform_fee": platform_fee,
            "net_amount": net_amount,
            "item_count": len(order_items)
        }
    
    def update_seller_balance(self, db: Session, seller_id: str, order_id: str, order_status: str, old_status: str = None):
        """
        Update seller balance when order status changes.
        Caller is responsible for db.commit() — this method does not commit.

        Balance lifecycle:
          processing  → pending_balance  += net  (payment initialised)
          paid        → no change        (stays in pending until delivery)
          shipped     → no change        (stays in pending until delivery)
          delivered   → pending_balance  -= net, available_balance += net, total_revenue += gross
          cancelled (from processing)  → pending_balance  -= net
          cancelled (from paid/shipped)→ pending_balance  -= net
          cancelled (from delivered)   → available_balance -= net, total_revenue -= gross
        """
        try:
            seller = db.query(SellerProfile).filter(SellerProfile.id == seller_id).first()
            if not seller:
                logger.error(f"Seller not found: {seller_id}")
                return

            if order_status == old_status:
                logger.info(f"Skipping duplicate balance update for seller {seller_id}, order {order_id}: {order_status}")
                return

            earnings = self.calculate_seller_earnings(db, seller_id, order_id)

            if order_status == "delivered":
                # Money earnt only once buyer confirms receipt
                if old_status in ["processing", "paid", "shipped"]:
                    seller.pending_balance -= earnings["net_amount"]
                    seller.available_balance += earnings["net_amount"]
                    seller.total_revenue += earnings["gross_amount"]
                    logger.info(f"Seller {seller_id}: +{earnings['net_amount']} available (delivered)")

            elif order_status in ("paid", "shipped"):
                # Payment confirmed / shipped — keep funds in pending until delivery
                logger.info(f"Seller {seller_id}: order {order_status}, funds remain in pending_balance")

            elif order_status == "processing":
                if old_status in ["pending", None]:
                    seller.pending_balance += earnings["net_amount"]
                    logger.info(f"Seller {seller_id}: +{earnings['net_amount']} pending (processing)")

            elif order_status == "cancelled":
                if old_status in ["processing", "paid", "shipped"]:
                    seller.pending_balance -= earnings["net_amount"]
                    logger.info(f"Seller {seller_id}: -{earnings['net_amount']} pending (cancelled from {old_status})")
                elif old_status == "delivered":
                    seller.available_balance -= earnings["net_amount"]
                    seller.total_revenue -= earnings["gross_amount"]
                    logger.info(f"Seller {seller_id}: -{earnings['net_amount']} available (cancelled from delivered)")

            # Guard against negative balances
            if seller.pending_balance < 0:
                logger.warning(f"Seller {seller_id} pending_balance clamped from {seller.pending_balance} to 0")
                seller.pending_balance = Decimal("0")
            if seller.available_balance < 0:
                logger.warning(f"Seller {seller_id} available_balance clamped from {seller.available_balance} to 0")
                seller.available_balance = Decimal("0")

        except Exception as e:
            logger.error(f"Failed to update seller balance for {seller_id}: {e}")
            raise
    
    def create_payout(self, db: Session, seller_id: str, amount: Decimal, 
                     account_number: str, bank_code: str, bank_name: str) -> SellerPayout:
        """
        Create a payout request for a seller
        
        Args:
            seller_id: Seller ID
            amount: Payout amount
            account_number: Bank account number
            bank_code: Bank code
            bank_name: Bank name
            
        Returns:
            Created SellerPayout object
        """
        try:
            seller = db.query(SellerProfile).filter(SellerProfile.id == seller_id).first()
            if not seller:
                raise ValueError("Seller not found")
            
            # Check if seller has sufficient balance
            if seller.available_balance < amount:
                raise ValueError("Insufficient balance for payout")

            minimum_payout_amount = self.get_minimum_payout_amount(db)
            if Decimal(str(amount)) < minimum_payout_amount:
                raise ValueError(f"Minimum payout amount is ₦{minimum_payout_amount:,.2f}")
            
            # Platform fee already deducted when earnings were calculated — no second deduction
            platform_fee = Decimal('0')
            net_amount = amount

            # Lock the balance immediately so concurrent requests can't double-spend
            seller.available_balance -= amount

            # Create payout record
            payout = SellerPayout(
                seller_id=seller_id,
                amount=amount,
                platform_fee=platform_fee,
                net_amount=net_amount,
                status="pending",
                account_number=account_number,
                bank_code=bank_code,
                bank_name=bank_name,
                transfer_reference=f"PAYOUT_{uuid.uuid4().hex[:12].upper()}"
            )
            
            db.add(payout)
            db.commit()
            db.refresh(payout)

            logger.info(f"Created payout {payout.id} for seller {seller_id}: {amount}")

            # Send confirmation email to seller
            try:
                from core.model import User
                from core.tasks import send_payout_requested_email
                user = db.query(User).filter(User.id == seller_id).first()
                if user:
                    send_payout_requested_email.delay(
                        seller_email=user.email,
                        business_name=seller.business_name,
                        amount=f"₦{float(amount):,.2f}",
                        bank_name=bank_name,
                        account_number=account_number,
                    )
            except Exception as e:
                logger.warning(f"Failed to send payout requested email: {e}")

            return payout
            
        except Exception as e:
            logger.error(f"Failed to create payout for seller {seller_id}: {e}")
            db.rollback()
            raise
    
    def process_payout(self, db: Session, payout_id: str) -> bool:
        """
        Process a payout using Paystack
        
        Args:
            payout_id: Payout ID to process
            
        Returns:
            True if successful, False otherwise
        """
        try:
            payout = db.query(SellerPayout).filter(SellerPayout.id == payout_id).first()
            if not payout:
                logger.error(f"Payout not found: {payout_id}")
                return False
            
            seller = db.query(SellerProfile).filter(SellerProfile.id == payout.seller_id).first()
            if not seller:
                logger.error(f"Seller not found for payout {payout_id}")
                return False
            
            # Check if seller has Paystack recipient code
            if not seller.payout_recipient_code:
                # Create recipient if not exists
                recipient_data = self.paystack_service.create_transfer_recipient(
                    name=seller.business_name,
                    account_number=payout.account_number,
                    bank_code=payout.bank_code,
                    email=seller.contact_email or f"seller_{seller.id}@lel-marketplace.com"
                )
                
                if recipient_data.get("status"):
                    seller.payout_recipient_code = recipient_data["data"]["recipient_code"]
                    db.commit()
                else:
                    payout.status = "failed"
                    payout.failure_reason = "Failed to create transfer recipient"
                    db.commit()
                    system_settings_service.notify_admins(
                        db=db,
                        event_key="system_alert",
                        title="Payout Recipient Setup Failed",
                        message=f"Failed to create a payout recipient for seller {seller.business_name}.",
                        data={
                            "seller_id": str(seller.id),
                            "payout_id": str(payout.id),
                        },
                        priority="high",
                    )
                    return False
            
            # Initiate transfer
            transfer_data = self.paystack_service.initiate_transfer(
                amount=int(payout.net_amount * 100),  # Convert to kobo
                recipient_code=seller.payout_recipient_code,
                reference=payout.transfer_reference,
                reason=f"Seller payout for {seller.business_name}"
            )
            
            if transfer_data.get("status"):
                payout.status = "processing"
                payout.paystack_transfer_id = transfer_data["data"]["transfer_code"]
                payout.processed_at = datetime.utcnow()
                
                # Deduct from seller's available balance
                seller.available_balance -= payout.amount
                seller.total_paid += payout.net_amount
                
                db.commit()
                
                logger.info(f"Payout {payout_id} processing initiated")
                return True
            else:
                payout.status = "failed"
                payout.failure_reason = "Paystack transfer failed"
                db.commit()
                system_settings_service.notify_admins(
                    db=db,
                    event_key="system_alert",
                    title="Payout Processing Failed",
                    message=f"Paystack transfer failed for payout {payout.id}.",
                    data={"payout_id": str(payout.id)},
                    priority="high",
                )
                return False
                
        except Exception as e:
            logger.error(f"Failed to process payout {payout_id}: {e}")
            if payout:
                payout.status = "failed"
                payout.failure_reason = str(e)
                db.commit()
                system_settings_service.notify_admins(
                    db=db,
                    event_key="system_alert",
                    title="Payout Processing Error",
                    message=f"An exception occurred while processing payout {payout_id}.",
                    data={"payout_id": str(payout_id), "error": str(e)},
                    priority="high",
                )
            return False
    
    def get_seller_payouts(self, db: Session, seller_id: str, limit: int = 20, 
                          page: int = 1) -> Tuple[List[SellerPayout], int]:
        """
        Get seller payout history
        
        Args:
            seller_id: Seller ID
            limit: Number of records per page
            page: Page number
            
        Returns:
            Tuple of (payouts, total_count)
        """
        offset = (page - 1) * limit
        
        payouts = (
            db.query(SellerPayout)
            .filter(SellerPayout.seller_id == seller_id)
            .order_by(desc(SellerPayout.created_at))
            .offset(offset)
            .limit(limit)
            .all()
        )
        
        total_count = (
            db.query(SellerPayout)
            .filter(SellerPayout.seller_id == seller_id)
            .count()
        )
        
        return payouts, total_count
    
    def get_pending_payouts(self, db: Session, limit: int = 50) -> List[SellerPayout]:
        """
        Get all pending payouts for admin processing
        
        Args:
            limit: Maximum number of payouts to return
            
        Returns:
            List of pending payouts
        """
        return (
            db.query(SellerPayout)
            .filter(SellerPayout.status == "pending")
            .order_by(SellerPayout.created_at)
            .limit(limit)
            .all()
        )
    
    def handle_payout_webhook(self, db: Session, transfer_data: Dict[str, Any]):
        """
        Handle Paystack transfer webhook events
        
        Args:
            transfer_data: Webhook data from Paystack
        """
        try:
            transfer_code = transfer_data.get("transfer_code")
            status = transfer_data.get("status")
            
            if not transfer_code:
                logger.error("No transfer_code in webhook data")
                return
            
            # Find payout by Paystack transfer ID
            payout = (
                db.query(SellerPayout)
                .filter(SellerPayout.paystack_transfer_id == transfer_code)
                .first()
            )
            
            if not payout:
                logger.error(f"Payout not found for transfer {transfer_code}")
                return
            
            if status == "success":
                payout.status = "completed"
                payout.processed_at = datetime.utcnow()
                
                # Create success notification (data keys trigger specific email template)
                seller_for_notif = db.query(SellerProfile).filter(
                    SellerProfile.id == payout.seller_id).first()
                create_notification(db, {
                    "user_id": str(payout.seller_id),
                    "type": "payment_successful",
                    "title": "Payout Completed",
                    "message": f"Your payout of ₦{payout.net_amount:,.2f} has been processed successfully.",
                    "priority": "high",
                    "channels": ["in_app", "email"],
                    "data": {
                        "payout_id": str(payout.id),
                        "amount": float(payout.net_amount),
                        "bank_name": payout.bank_name,
                        "transfer_reference": payout.transfer_reference,
                        "business_name": seller_for_notif.business_name if seller_for_notif else "",
                    },
                })
                
                logger.info(f"Payout {payout.id} completed successfully")
                try:
                    send_payout_completed_email.delay(
                        seller_for_notif.contact_email,
                        seller_for_notif.business_name,
                        f"₦{payout.net_amount:,.2f}",
                        payout.bank_name,
                        payout.transfer_reference,
                    )
                except Exception as e:
                    logger.error(f"Failed to queue payout completed email: {e}")

            elif status == "failed":
                payout.status = "failed"
                payout.failure_reason = transfer_data.get("failure_reason", "Transfer failed")
                
                # Refund to seller's available balance
                seller = db.query(SellerProfile).filter(SellerProfile.id == payout.seller_id).first()
                if seller:
                    seller.available_balance += payout.amount
                    seller.total_paid -= payout.net_amount
                
                # Create failure notification (data keys trigger specific email template)
                create_notification(db, {
                    "user_id": str(payout.seller_id),
                    "type": "payment_failed",
                    "title": "Payout Failed",
                    "message": f"Your payout of ₦{payout.net_amount:,.2f} failed. Amount has been refunded to your balance.",
                    "priority": "high",
                    "channels": ["in_app", "email"],
                    "data": {
                        "payout_id": str(payout.id),
                        "amount": float(payout.net_amount),
                        "failure_reason": payout.failure_reason
                    }
                })
                
                logger.warning(f"Payout {payout.id} failed: {payout.failure_reason}")
                if seller:
                    try:
                        send_payout_failed_email.delay(
                            seller.contact_email,
                            seller.business_name,
                            f"₦{payout.net_amount:,.2f}",
                            payout.failure_reason,
                        )
                    except Exception as e:
                        logger.error(f"Failed to queue payout failed email: {e}")

            db.commit()
            
        except Exception as e:
            logger.error(f"Failed to handle payout webhook: {e}")
            db.rollback()

# Global instance
seller_payout_service = SellerPayoutService()
