import requests
import logging
import hmac
import hashlib
from datetime import datetime, timedelta, timezone
from typing import Dict, Any, Optional
from core.config import settings

logger = logging.getLogger(__name__)

class PaystackService:
    def __init__(self):
        self.secret_key = settings.PAYSTACK_SECRET_KEY
        self.public_key = settings.PAYSTACK_PUBLIC_KEY
        self.base_url = "https://api.paystack.co"
        self.headers = {
            "Authorization": f"Bearer {self.secret_key}",
            "Content-Type": "application/json"
        }
        
        # Check if keys are configured
        if not self.secret_key or not self.public_key:
            logger.warning("Paystack keys not configured. Payment functionality will not work.")
        
        self.webhook_secret = settings.PAYSTACK_WEBHOOK_SECRET

    def initialize_transaction(self, email: str, amount: int, reference: str, metadata: Optional[Dict] = None, callback_url: Optional[str] = None) -> Dict[str, Any]:
        """
        Initialize a Paystack transaction
        
        Args:
            email: Customer email
            amount: Amount in kobo (NGN)
            reference: Unique transaction reference
            metadata: Additional data to store with transaction
            
        Returns:
            Dict containing transaction details
        """
        # Check if keys are configured
        if not self.secret_key or not self.public_key:
            logger.warning("Paystack keys not configured. Using mock payment for development.")
            # Return mock response for development
            return {
                "status": True,
                "message": "Authorization URL created",
                "data": {
                    "authorization_url": f"https://checkout.paystack.com/mock/{reference}",
                    "access_code": f"mock_{reference}",
                    "reference": reference
                }
            }
        
        try:
            url = f"{self.base_url}/transaction/initialize"
            payload = {
                "email": email,
                "amount": amount,
                "reference": reference,
                "metadata": metadata or {},
                "callback_url": callback_url
            }
            if not callback_url:
                 payload.pop("callback_url")
            
            response = requests.post(url, json=payload, headers=self.headers)
            response.raise_for_status()
            
            data = response.json()
            logger.info(f"Paystack transaction initialized: {reference}")
            return data
            
        except requests.exceptions.RequestException as e:
            logger.error(f"Paystack API error: {str(e)}")
            raise Exception(f"Failed to initialize payment: {str(e)}")

    def verify_transaction(self, reference: str) -> Dict[str, Any]:
        """
        Verify a Paystack transaction
        
        Args:
            reference: Transaction reference to verify
            
        Returns:
            Dict containing transaction verification details
        """
        # Check if keys are configured
        if not self.secret_key or not self.public_key:
            logger.warning("Paystack keys not configured. Using mock verification for development.")
            # Return mock successful verification for development
            return {
                "status": True,
                "message": "Verification successful",
                "data": {
                    "id": 123456789,
                    "domain": "test",
                    "status": "success",
                    "reference": reference,
                    "amount": 100000,  # Mock amount in kobo
                    "message": None,
                    "gateway_response": "Successful",
                    "paid_at": "2024-01-01T00:00:00.000Z",
                    "created_at": "2024-01-01T00:00:00.000Z",
                    "channel": "card",
                    "currency": "NGN",
                    "ip_address": "127.0.0.1",
                    "metadata": {},
                    "log": None,
                    "fees": 1500,
                    "fees_split": None,
                    "authorization": {
                        "authorization_code": f"mock_auth_{reference}",
                        "bin": "408408",
                        "last4": "4081",
                        "exp_month": "12",
                        "exp_year": "2030",
                        "channel": "card",
                        "card_type": "visa",
                        "bank": "TEST BANK",
                        "country_code": "NG",
                        "brand": "visa",
                        "reusable": True,
                        "signature": f"mock_sig_{reference}",
                        "account_name": None
                    },
                    "customer": {
                        "id": 123456,
                        "first_name": "Test",
                        "last_name": "Customer",
                        "email": "test@example.com",
                        "customer_code": f"mock_customer_{reference}",
                        "phone": None,
                        "metadata": None,
                        "risk_action": "default"
                    },
                    "plan": None,
                    "split": {},
                    "order_id": None,
                    "paidAt": "2024-01-01T00:00:00.000Z",
                    "createdAt": "2024-01-01T00:00:00.000Z",
                    "requested_amount": 100000,
                    "pos_transaction_data": None,
                    "source": None,
                    "fees_breakdown": None
                }
            }
        
        try:
            url = f"{self.base_url}/transaction/verify/{reference}"
            
            response = requests.get(url, headers=self.headers)
            response.raise_for_status()
            
            data = response.json()
            logger.info(f"Paystack transaction verified: {reference}")
            return data
            
        except requests.exceptions.RequestException as e:
            logger.error(f"Paystack verification error: {str(e)}")
            raise Exception(f"Failed to verify payment: {str(e)}")

    def charge_bank_transfer(self, email: str, amount: int, reference: str, metadata: Optional[Dict] = None, account_expires_at: Optional[str] = None) -> Dict[str, Any]:
        """
        Initiate a "Pay with Transfer" charge - generates a one-time bank account
        number tied to this transaction for the customer to transfer funds to.

        Args:
            email: Customer email
            amount: Amount in kobo (NGN)
            reference: Unique transaction reference
            metadata: Additional data to store with transaction
            account_expires_at: Optional ISO8601 expiry for the generated account
                (Paystack defaults to 15 minutes, capped at 8 hours)

        Returns:
            Dict containing charge details, including a `bank_transfer` block with
            the account number, bank name and account name to display to the customer
        """
        if not self.secret_key or not self.public_key:
            logger.warning("Paystack keys not configured. Using mock bank transfer charge for development.")
            if not account_expires_at:
                expires_dt = datetime.now(timezone.utc) + timedelta(hours=1)
                account_expires_at = expires_dt.strftime("%Y-%m-%dT%H:%M:%S.000Z")
            return {
                "status": True,
                "message": "Charge attempted",
                "data": {
                    "reference": reference,
                    "status": "pending_bank_transfer",
                    "display_text": "Make a bank transfer to the account below to complete this payment.",
                    "amount": amount,
                    "currency": "NGN",
                    "account_number": "9999999999",
                    "account_name": "MOCK/PAYSTACK TEST ACCOUNT",
                    "bank": {"slug": "test-bank", "name": "Test Bank", "id": 24},
                    "account_expires_at": account_expires_at
                }
            }

        try:
            url = f"{self.base_url}/charge"
            if not account_expires_at:
                # Paystack requires account_expires_at to be present and in the future
                expires_dt = datetime.now(timezone.utc) + timedelta(hours=1)
                account_expires_at = expires_dt.strftime("%Y-%m-%dT%H:%M:%S.000Z")

            payload = {
                "email": email,
                "amount": amount,
                "reference": reference,
                "metadata": metadata or {},
                "bank_transfer": {"account_expires_at": account_expires_at}
            }

            response = requests.post(url, json=payload, headers=self.headers)
            response.raise_for_status()

            data = response.json()
            logger.info(f"Paystack bank transfer charge initiated: {reference}")
            return data

        except requests.exceptions.RequestException as e:
            logger.error(f"Paystack bank transfer charge error: {str(e)}")
            raise Exception(f"Failed to initiate bank transfer charge: {str(e)}")

    def get_banks(self) -> Dict[str, Any]:
        """
        Get list of supported banks
        
        Returns:
            Dict containing list of banks
        """
        try:
            url = f"{self.base_url}/bank"
            
            response = requests.get(url, headers=self.headers)
            response.raise_for_status()
            
            data = response.json()
            return data
            
        except requests.exceptions.RequestException as e:
            logger.error(f"Paystack banks error: {str(e)}")
            raise Exception(f"Failed to get banks: {str(e)}")

    def get_transaction_status(self, reference: str) -> Dict[str, Any]:
        """
        Get transaction status
        
        Args:
            reference: Transaction reference
            
        Returns:
            Dict containing transaction status
        """
        try:
            url = f"{self.base_url}/transaction/{reference}"
            
            response = requests.get(url, headers=self.headers)
            response.raise_for_status()
            
            data = response.json()
            return data
            
        except requests.exceptions.RequestException as e:
            logger.error(f"Paystack status error: {str(e)}")
            raise Exception(f"Failed to get transaction status: {str(e)}")

    def initiate_refund(self, reference: str, amount: Optional[int] = None, customer_note: str = "Refund processed") -> Dict[str, Any]:
        """
        Initiate a refund for a successful Paystack transaction
        
        Args:
            reference: Transaction reference to refund
            amount: Optional amount in kobo (NGN). If not provided, refunds entire amount.
            customer_note: Note to customer
            
        Returns:
            Dict containing refund details
        """
        if not self.secret_key or not self.public_key:
            logger.warning("Paystack keys not configured. Using mock refund for development.")
            return {
                "status": True,
                "message": "Refund has been queued for processing",
                "data": {
                    "transaction": {"reference": reference},
                    "integration": 123456,
                    "deducted_amount": amount or 0,
                    "channel": "backend",
                    "merchant_note": "Mock refund",
                    "customer_note": customer_note,
                    "status": "pending",
                    "refunded_by": "System",
                    "expected_at": "2024-01-01T00:00:00.000Z",
                    "currency": "NGN",
                    "domain": "test",
                    "amount": amount or 0,
                    "fully_deducted": False,
                    "id": 1234,
                    "createdAt": "2024-01-01T00:00:00.000Z",
                    "updatedAt": "2024-01-01T00:00:00.000Z"
                }
            }
            
        try:
            url = f"{self.base_url}/refund"
            payload = {
                "transaction": reference,
                "customer_note": customer_note
            }
            if amount is not None:
                payload["amount"] = amount
                
            response = requests.post(url, json=payload, headers=self.headers)
            response.raise_for_status()
            
            data = response.json()
            logger.info(f"Paystack refund initiated for: {reference}")
            return data
            
        except requests.exceptions.RequestException as e:
            logger.error(f"Paystack refund error: {str(e)}")
            raise Exception(f"Failed to initiate refund: {str(e)}")

    def verify_webhook_signature(self, payload: bytes, signature: str) -> bool:
        """
        Verify Paystack webhook signature using HMAC SHA512
        
        Args:
            payload: Raw webhook payload
            signature: X-Paystack-Signature header value
            
        Returns:
            bool: True if signature is valid
        """
        if not self.webhook_secret:
            logger.warning("Webhook secret not configured. Skipping signature verification.")
            return True  # Allow in development
        
        try:
            # Create HMAC signature
            expected_signature = hmac.new(
                self.webhook_secret.encode('utf-8'),
                payload,
                hashlib.sha512
            ).hexdigest()
            
            # Compare signatures using constant-time comparison
            return hmac.compare_digest(expected_signature, signature)
            
        except Exception as e:
            logger.error(f"Webhook signature verification failed: {str(e)}")
            return False

# Global instance
paystack_service = PaystackService()
