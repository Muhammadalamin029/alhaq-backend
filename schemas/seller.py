from pydantic import BaseModel, Field
from typing import Optional, List, Dict, Any
from datetime import datetime
from decimal import Decimal
from schemas.products import ProductResponse
from schemas.order import OrderResponse


class SellerProfileResponse(BaseModel):
    success: bool
    message: str
    data: "SellerProfileData"


class SellerProfileData(BaseModel):
    id: str
    business_name: str
    description: Optional[str] = None
    logo_url: Optional[str] = None
    contact_email: Optional[str] = None
    contact_phone: Optional[str] = None
    website_url: Optional[str] = None
    kyc_status: str
    approval_date: Optional[datetime] = None
    total_products: int = 0
    total_orders: int = 0
    total_revenue: Decimal = Decimal('0.00')
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


class SellerProfileUpdate(BaseModel):
    business_name: Optional[str] = Field(None, min_length=2, max_length=255)
    description: Optional[str] = Field(None, max_length=1000)
    logo_url: Optional[str] = Field(None, max_length=500)
    contact_email: Optional[str] = Field(None, max_length=255)
    contact_phone: Optional[str] = Field(None, max_length=50)
    website_url: Optional[str] = Field(None, max_length=500)

class SellerStatsResponse(BaseModel):
    success: bool
    message: str
    data: "SellerStatsData"


class SellerStatsData(BaseModel):
    total_products: int
    active_products: int
    out_of_stock_products: int
    total_orders: int
    pending_orders: int
    total_revenue: float
    kyc_status: str
    business_name: str
    # Enhanced dashboard data
    recent_orders: List[Dict[str, Any]] = []
    recent_products: List[Dict[str, Any]] = []
    revenue_trend: Optional[str] = None
    orders_trend: Optional[str] = None


class SellerProductsResponse(BaseModel):
    success: bool
    message: str
    data: List[ProductResponse]
    pagination: "PaginationMeta"


class SellerOrdersResponse(BaseModel):
    success: bool
    message: str
    data: List[OrderResponse]
    pagination: "PaginationMeta"


class SellerAnalyticsResponse(BaseModel):
    success: bool
    message: str
    data: "SellerAnalyticsData"


class RevenueDataPoint(BaseModel):
    date: str
    revenue: float
    orders: int
    
class OrderDataPoint(BaseModel):
    date: str
    orders: int
    total_value: float
    
class TopProduct(BaseModel):
    id: str
    name: str
    total_sold: int
    revenue: float
    stock_quantity: int
    
class ProductPerformance(BaseModel):
    id: str
    name: str
    views: int
    orders: int
    conversion_rate: float
    revenue: float
    
class CustomerInsight(BaseModel):
    total_customers: int
    repeat_customers: int
    repeat_rate: float
    average_order_value: float
    
class InventoryInsight(BaseModel):
    total_products: int
    active_products: int
    low_stock_products: int
    out_of_stock_products: int
    total_inventory_value: float

class SellerAnalyticsData(BaseModel):
    # Time series data
    revenue_data: List[RevenueDataPoint]
    order_data: List[OrderDataPoint]
    
    # Product insights
    top_products: List[TopProduct]
    product_performance: List[ProductPerformance]
    
    # Customer insights
    customer_insights: CustomerInsight
    
    # Inventory insights
    inventory_insights: InventoryInsight
    
    # Summary metrics
    total_revenue: float
    total_orders: int
    average_order_value: float
    revenue_growth: float
    order_growth: float
    
    # Period info
    period: str
    start_date: str
    end_date: str


class PaginationMeta(BaseModel):
    page: int
    limit: int
    total: int
    total_pages: int


# Update forward references
SellerProfileResponse.model_rebuild()
SellerStatsResponse.model_rebuild()
SellerProductsResponse.model_rebuild()
SellerOrdersResponse.model_rebuild()
SellerAnalyticsResponse.model_rebuild()
