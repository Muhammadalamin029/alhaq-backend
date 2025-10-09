"""
Bank service for fetching and managing bank data from Paystack
"""

import requests
import json
from typing import List, Dict, Optional
from datetime import datetime, timedelta
from core.config import settings
from core.logging_config import get_logger
from core.redis_client import redis_client
import asyncio

bank_logger = get_logger("core.bank_service")

class BankService:
    def __init__(self):
        self.paystack_secret_key = settings.PAYSTACK_SECRET_KEY
        self.base_url = "https://api.paystack.co"
        self.cache_key = "paystack_banks"
        self.cache_expiry = 24 * 60 * 60  # 24 hours in seconds
    
    async def fetch_banks_from_paystack(self) -> List[Dict]:
        """Fetch banks from Paystack API"""
        try:
            url = f"{self.base_url}/bank"
            headers = {
                "Authorization": f"Bearer {self.paystack_secret_key}",
                "Content-Type": "application/json"
            }
            
            bank_logger.info("Fetching banks from Paystack API")
            response = requests.get(url, headers=headers, timeout=30)
            
            if response.status_code == 200:
                data = response.json()
                if data.get("status"):
                    banks = data.get("data", [])
                    bank_logger.info(f"Successfully fetched {len(banks)} banks from Paystack")
                    return banks
                else:
                    bank_logger.error(f"Paystack API returned error: {data.get('message', 'Unknown error')}")
                    return []
            else:
                bank_logger.error(f"Failed to fetch banks from Paystack. Status: {response.status_code}, Response: {response.text}")
                return []
                
        except requests.exceptions.RequestException as e:
            bank_logger.error(f"Request error while fetching banks: {str(e)}")
            return []
        except Exception as e:
            bank_logger.error(f"Unexpected error while fetching banks: {str(e)}")
            return []
    
    async def get_banks(self, force_refresh: bool = False) -> List[Dict]:
        """Get banks from cache or fetch from Paystack"""
        try:
            # Check cache first (unless force refresh)
            if not force_refresh:
                cached_banks = redis_client.get(self.cache_key, as_json=True)
                if cached_banks:
                    bank_logger.info("Retrieved banks from cache")
                    return cached_banks
            
            # Fetch from Paystack
            banks = await self.fetch_banks_from_paystack()
            
            if banks:
                # Cache the banks data
                redis_client.set(
                    self.cache_key, 
                    banks,
                    expire=self.cache_expiry
                )
                bank_logger.info(f"Cached {len(banks)} banks for {self.cache_expiry} seconds")
            
            return banks
            
        except Exception as e:
            bank_logger.error(f"Error in get_banks: {str(e)}")
            return []
    
    async def get_bank_by_code(self, bank_code: str) -> Optional[Dict]:
        """Get a specific bank by its code"""
        try:
            banks = await self.get_banks()
            for bank in banks:
                if bank.get("code") == bank_code:
                    return bank
            return None
        except Exception as e:
            bank_logger.error(f"Error getting bank by code {bank_code}: {str(e)}")
            return None
    
    async def search_banks(self, query: str) -> List[Dict]:
        """Search banks by name or code"""
        try:
            banks = await self.get_banks()
            query_lower = query.lower()
            
            filtered_banks = []
            for bank in banks:
                name = bank.get("name", "").lower()
                code = bank.get("code", "").lower()
                
                if query_lower in name or query_lower in code:
                    filtered_banks.append(bank)
            
            return filtered_banks
        except Exception as e:
            bank_logger.error(f"Error searching banks: {str(e)}")
            return []
    
    async def refresh_banks_cache(self) -> bool:
        """Force refresh the banks cache"""
        try:
            banks = await self.fetch_banks_from_paystack()
            if banks:
                redis_client.set(
                    self.cache_key, 
                    banks,
                    expire=self.cache_expiry
                )
                bank_logger.info("Banks cache refreshed successfully")
                return True
            return False
        except Exception as e:
            bank_logger.error(f"Error refreshing banks cache: {str(e)}")
            return False

# Create a singleton instance
bank_service = BankService()
