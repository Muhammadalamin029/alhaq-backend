from sqlalchemy.orm import Session
from typing import Dict, Any
from decimal import Decimal
import logging

from core.model import SellerProfile, OrderItem, Product
from core.system_settings_service import system_settings_service

logger = logging.getLogger(__name__)

class CommissionService:
    """Service for tracking seller earnings/balances (commission + revenue accounting).

    Note: actual bank-transfer payout processing (create_payout/process_payout/
    handle_payout_webhook) was removed in the single-vendor migration along with
    the seller_payouts table. This service now only computes platform fees and
    keeps SellerProfile balance columns in sync with order lifecycle events -
    logic still used by checkout/order flows and the admin revenue dashboard.
    """

    # Platform commission rate (5%)
    PLATFORM_FEE_RATE = Decimal('0.05')

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

# Global instance
commission_service = CommissionService()
