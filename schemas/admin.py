from pydantic import BaseModel, EmailStr, Field, validator
from typing import Optional, List, Dict, Any
from datetime import datetime, date
from enum import Enum
from decimal import Decimal
from uuid import UUID

# ---------------- ENUMS ----------------
class UserActionType(str, Enum):
    LOCK_ACCOUNT = "lock_account"
    UNLOCK_ACCOUNT = "unlock_account"
    VERIFY_EMAIL = "verify_email"
    RESET_LOGIN_ATTEMPTS = "reset_login_attempts"


class SellerActionType(str, Enum):
    APPROVE_KYC = "approve_kyc"
    REJECT_KYC = "reject_kyc"
    LOCK_ACCOUNT = "lock_account"
    UNLOCK_ACCOUNT = "unlock_account"


class ProductActionType(str, Enum):
    ACTIVATE = "activate"
    DEACTIVATE = "deactivate"
    LOCK = "lock"  # Admin lock - different from seller deactivate
    DELETE = "delete"


# ---------------- USER MANAGEMENT ----------------
class AdminUserListResponse(BaseModel):
    """Admin view of user list - matches User model"""
    id: UUID
    email: str
    role: str
    email_verified: bool
    email_verified_at: Optional[datetime] = None
    failed_login_attempts: int
    locked_until: Optional[datetime] = None
    last_login: Optional[datetime] = None
    created_at: datetime
    updated_at: datetime
    profile_name: Optional[str] = None  # From Profile.name or SellerProfile.business_name
    
    class Config:
        from_attributes = True


class AdminUserDetailResponse(BaseModel):
    """Detailed admin view of a user - matches User + Profile models"""
    # User fields
    id: UUID
    email: str
    role: str
    email_verified: bool
    email_verified_at: Optional[datetime] = None
    failed_login_attempts: int
    locked_until: Optional[datetime] = None
    last_login: Optional[datetime] = None
    password_changed_at: datetime
    two_factor_enabled: bool
    created_at: datetime
    updated_at: datetime
    
    # Profile fields (customer or seller)
    profile_name: Optional[str] = None
    profile_bio: Optional[str] = None
    profile_avatar: Optional[str] = None
    kyc_status: Optional[str] = None
    approval_date: Optional[date] = None
    
    # Seller specific fields
    business_name: Optional[str] = None
    contact_email: Optional[str] = None
    contact_phone: Optional[str] = None
    website_url: Optional[str] = None
    logo_url: Optional[str] = None
    total_products: Optional[int] = None
    total_orders: Optional[int] = None
    total_revenue: Optional[Decimal] = None
    
    # Admin calculated fields
    order_count: int = 0
    total_spent: Decimal = Decimal('0.00')
    
    class Config:
        from_attributes = True


class AdminUserActionRequest(BaseModel):
    """Request for admin user actions"""
    action: UserActionType
    reason: Optional[str] = Field(None, max_length=500)
    lock_duration_hours: Optional[int] = Field(None, ge=1, le=8760)  # Max 1 year


# ---------------- SELLER MANAGEMENT ----------------
class AdminSellerListResponse(BaseModel):
    """Admin view of seller list - matches SellerProfile model"""
    id: UUID
    email: str  # From User
    business_name: str
    description: Optional[str] = None
    contact_email: Optional[str] = None
    contact_phone: Optional[str] = None
    website_url: Optional[str] = None
    kyc_status: str
    approval_date: Optional[date] = None
    total_products: int
    total_orders: int
    total_revenue: Decimal
    created_at: datetime
    updated_at: datetime
    user_locked: Optional[datetime] = None  # From User.locked_until
    
    class Config:
        from_attributes = True


class AdminSellerActionRequest(BaseModel):
    """Request for admin seller actions"""
    action: SellerActionType
    reason: Optional[str] = Field(None, max_length=500)
    lock_duration_hours: Optional[int] = Field(None, ge=1, le=8760)


# ---------------- PRODUCT MANAGEMENT ----------------
class AdminProductListResponse(BaseModel):
    """Admin view of product list - matches Product model"""
    id: UUID
    name: str
    description: Optional[str] = None
    price: Decimal
    stock_quantity: int
    status: str
    created_at: datetime
    updated_at: datetime
    seller_id: UUID
    seller_name: str  # From SellerProfile.business_name
    category_id: UUID
    category_name: str  # From Category.name
    
    class Config:
        from_attributes = True


class AdminProductCreateRequest(BaseModel):
    """Admin create product request - matches Product model"""
    seller_id: UUID
    name: str = Field(..., min_length=1, max_length=255)
    description: Optional[str] = Field(None, max_length=2000)
    price: Decimal = Field(..., gt=0, decimal_places=2)
    stock_quantity: int = Field(0, ge=0)
    category_id: UUID
    status: str = Field("active", pattern="^(active|inactive|out_of_stock)$")


class AdminProductUpdateRequest(BaseModel):
    """Admin update product request"""
    name: Optional[str] = Field(None, min_length=1, max_length=255)
    description: Optional[str] = Field(None, max_length=2000)
    price: Optional[Decimal] = Field(None, gt=0, decimal_places=2)
    stock_quantity: Optional[int] = Field(None, ge=0)
    category_id: Optional[UUID] = None
    status: Optional[str] = Field(None, pattern="^(active|inactive|out_of_stock)$")


class AdminProductActionRequest(BaseModel):
    """Request for admin product actions"""
    action: ProductActionType
    reason: Optional[str] = Field(None, max_length=500)


# ---------------- ORDER MANAGEMENT ----------------
class AdminOrderListResponse(BaseModel):
    """Admin view of order list - matches Order model"""
    id: UUID
    buyer_id: UUID
    buyer_name: str  # From Profile.name
    buyer_email: str  # From User.email
    total_amount: Decimal
    status: str
    delivery_address: Optional[UUID] = None
    created_at: datetime
    updated_at: datetime
    items_count: int  # Calculated
    
    class Config:
        from_attributes = True


# ---------------- DASHBOARD & ANALYTICS ----------------
class AdminDashboardStats(BaseModel):
    """Admin dashboard statistics - matches AdminStats model"""
    total_users: int
    total_products: int
    total_orders: int
    total_payments: int
    total_revenue: Decimal
    
    # Today's stats
    new_users_today: int
    new_orders_today: int
    revenue_today: Decimal
    
    # Status counts
    pending_seller_approvals: int
    locked_users: int
    out_of_stock_products: int
    pending_orders: int
    
    class Config:
        from_attributes = True


class AdminRevenueByPeriod(BaseModel):
    """Revenue analytics by time period"""
    date: str
    revenue: Decimal
    orders: int


class AdminTopSeller(BaseModel):
    """Top seller analytics"""
    seller_id: UUID
    business_name: str
    total_revenue: Decimal
    total_orders: int
    total_products: int


class AdminTopProduct(BaseModel):
    """Top product analytics"""
    product_id: UUID
    product_name: str
    seller_name: str
    total_sold: int
    total_revenue: Decimal


class AdminAnalyticsResponse(BaseModel):
    """Complete admin analytics"""
    dashboard_stats: AdminDashboardStats
    revenue_last_30_days: List[AdminRevenueByPeriod]
    top_sellers: List[AdminTopSeller]
    top_products: List[AdminTopProduct]


# ---------------- FILTERS & PAGINATION ----------------
class AdminUserListFilters(BaseModel):
    """Filters for admin user list"""
    role: Optional[str] = Field(None, pattern="^(customer|seller|admin)$")
    email_verified: Optional[bool] = None
    is_locked: Optional[bool] = None
    search: Optional[str] = Field(None, max_length=255)  # Search email or name
    created_after: Optional[date] = None
    created_before: Optional[date] = None
    page: int = Field(1, ge=1)
    limit: int = Field(20, ge=1, le=100)


class AdminSellerListFilters(BaseModel):
    """Filters for admin seller list"""
    kyc_status: Optional[str] = Field(None, pattern="^(pending|approved|rejected)$")
    is_locked: Optional[bool] = None
    search: Optional[str] = Field(None, max_length=255)  # Search business name or email
    approval_after: Optional[date] = None
    approval_before: Optional[date] = None
    page: int = Field(1, ge=1)
    limit: int = Field(20, ge=1, le=100)


class AdminProductListFilters(BaseModel):
    """Filters for admin product list"""
    seller_id: Optional[UUID] = None
    category_id: Optional[UUID] = None
    status: Optional[str] = Field(None, pattern="^(active|inactive|out_of_stock)$")
    search: Optional[str] = Field(None, max_length=255)  # Search product name
    low_stock: Optional[bool] = None  # Products with stock < 10
    created_after: Optional[date] = None
    created_before: Optional[date] = None
    page: int = Field(1, ge=1)
    limit: int = Field(20, ge=1, le=100)


class AdminOrderListFilters(BaseModel):
    """Filters for admin order list"""
    status: Optional[str] = Field(None, pattern="^(pending|processing|shipped|delivered|cancelled)$")
    buyer_id: Optional[UUID] = None
    created_after: Optional[date] = None
    created_before: Optional[date] = None
    min_amount: Optional[Decimal] = Field(None, ge=0)
    max_amount: Optional[Decimal] = Field(None, ge=0)
    page: int = Field(1, ge=1)
    limit: int = Field(20, ge=1, le=100)


class AdminProductListResponse(BaseModel):
    """Product list item for admin"""
    id: UUID
    name: str
    description: Optional[str] = None
    price: Decimal
    stock_quantity: int
    status: str
    seller_id: UUID
    seller_name: str
    category_id: Optional[UUID] = None
    category_name: str
    images_count: int
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


class AdminProductListFilters(BaseModel):
    """Filters for admin product list"""
    seller_id: Optional[UUID] = None
    category_id: Optional[UUID] = None
    status: Optional[str] = Field(None, pattern="^(active|inactive|pending)$")
    search: Optional[str] = Field(None, max_length=255)
    min_price: Optional[Decimal] = Field(None, ge=0)
    max_price: Optional[Decimal] = Field(None, ge=0)
    created_after: Optional[date] = None
    created_before: Optional[date] = None
    page: int = Field(1, ge=1)
    limit: int = Field(20, ge=1, le=100)


class AdminProductActionRequest(BaseModel):
    """Request for admin product actions"""
    action: str = Field(..., pattern="^(approve|reject|disable)$")
    notes: Optional[str] = Field(None, max_length=500)


# ---------------- RESPONSE WRAPPERS ----------------
class AdminResponse(BaseModel):
    """Standard admin API response"""
    success: bool
    message: str
    data: Optional[Any] = None


class AdminListResponse(BaseModel):
    """Admin list response with pagination"""
    success: bool
    message: str
    data: List[Any]
    pagination: Dict[str, Any]
    total: int


class AdminPaginationInfo(BaseModel):
    """Pagination information"""
    page: int
    limit: int
    total: int
    total_pages: int
    has_next: bool
    has_prev: bool