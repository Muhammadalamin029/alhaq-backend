"""
Bank API endpoints for fetching and managing bank data
"""

from fastapi import APIRouter, HTTPException, status, Depends, Query
from typing import List, Optional
from core.bank_service import bank_service
from schemas.bank import BankListResponse, BankSearchRequest, BankSearchResponse, BankData
from core.logging_config import get_logger

router = APIRouter(prefix="/banks", tags=["banks"])
bank_logger = get_logger("routers.banks")

@router.get("/", response_model=BankListResponse)
async def get_banks(
    force_refresh: bool = Query(False, description="Force refresh from Paystack API")
):
    """Get list of all banks from Paystack"""
    try:
        bank_logger.info(f"Fetching banks, force_refresh: {force_refresh}")
        
        banks_data = await bank_service.get_banks(force_refresh=force_refresh)
        
        if not banks_data:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Unable to fetch banks data at the moment"
            )
        
        # Convert to BankData objects
        banks = [BankData(**bank) for bank in banks_data]
        
        return BankListResponse(
            success=True,
            message=f"Successfully retrieved {len(banks)} banks",
            data=banks,
            total=len(banks)
        )
        
    except HTTPException:
        raise
    except Exception as e:
        bank_logger.error(f"Error fetching banks: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Internal server error while fetching banks"
        )

@router.get("/search", response_model=BankSearchResponse)
async def search_banks(
    query: str = Query(..., min_length=1, max_length=100, description="Search query for bank name or code")
):
    """Search banks by name or code"""
    try:
        bank_logger.info(f"Searching banks with query: {query}")
        
        banks_data = await bank_service.search_banks(query)
        
        # Convert to BankData objects
        banks = [BankData(**bank) for bank in banks_data]
        
        return BankSearchResponse(
            success=True,
            message=f"Found {len(banks)} banks matching '{query}'",
            data=banks,
            total=len(banks)
        )
        
    except Exception as e:
        bank_logger.error(f"Error searching banks: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Internal server error while searching banks"
        )

@router.get("/{bank_code}", response_model=BankData)
async def get_bank_by_code(bank_code: str):
    """Get a specific bank by its code"""
    try:
        bank_logger.info(f"Fetching bank with code: {bank_code}")
        
        bank_data = await bank_service.get_bank_by_code(bank_code)
        
        if not bank_data:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Bank with code '{bank_code}' not found"
            )
        
        return BankData(**bank_data)
        
    except HTTPException:
        raise
    except Exception as e:
        bank_logger.error(f"Error fetching bank by code {bank_code}: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Internal server error while fetching bank"
        )

@router.post("/refresh")
async def refresh_banks_cache():
    """Force refresh the banks cache from Paystack"""
    try:
        bank_logger.info("Refreshing banks cache")
        
        success = await bank_service.refresh_banks_cache()
        
        if success:
            return {
                "success": True,
                "message": "Banks cache refreshed successfully"
            }
        else:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Failed to refresh banks cache"
            )
        
    except HTTPException:
        raise
    except Exception as e:
        bank_logger.error(f"Error refreshing banks cache: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Internal server error while refreshing cache"
        )
