import requests
import logging
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

    def initialize_transaction(self, email: str, amount: int, reference: str, metadata: Optional[Dict] = None) -> Dict[str, Any]:
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
                "metadata": metadata or {}
            }
            
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

    def create_transfer_recipient(self, name: str, account_number: str, bank_code: str, email: str) -> Dict[str, Any]:
        """
        Create a transfer recipient for seller payouts
        
        Args:
            name: Recipient name
            account_number: Bank account number
            bank_code: Bank code from Paystack
            email: Recipient email
            
        Returns:
            Dict containing recipient details
        """
        try:
            url = f"{self.base_url}/transferrecipient"
            payload = {
                "type": "nuban",
                "name": name,
                "account_number": account_number,
                "bank_code": bank_code,
                "email": email
            }
            
            response = requests.post(url, json=payload, headers=self.headers)
            response.raise_for_status()
            
            data = response.json()
            logger.info(f"Paystack transfer recipient created: {email}")
            return data
            
        except requests.exceptions.RequestException as e:
            logger.error(f"Paystack recipient creation error: {str(e)}")
            raise Exception(f"Failed to create transfer recipient: {str(e)}")

    def initiate_transfer(self, amount: int, recipient_code: str, reference: str, reason: str = "Seller payout") -> Dict[str, Any]:
        """
        Initiate a transfer to a seller
        
        Args:
            amount: Amount in kobo (NGN)
            recipient_code: Paystack recipient code
            reference: Transfer reference
            reason: Transfer reason
            
        Returns:
            Dict containing transfer details
        """
        try:
            url = f"{self.base_url}/transfer"
            payload = {
                "source": "balance",
                "amount": amount,
                "recipient": recipient_code,
                "reference": reference,
                "reason": reason
            }
            
            response = requests.post(url, json=payload, headers=self.headers)
            response.raise_for_status()
            
            data = response.json()
            logger.info(f"Paystack transfer initiated: {reference}")
            return data
            
        except requests.exceptions.RequestException as e:
            logger.error(f"Paystack transfer error: {str(e)}")
            raise Exception(f"Failed to initiate transfer: {str(e)}")

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

# Global instance
paystack_service = PaystackService()
