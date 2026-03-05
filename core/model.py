from db.session import Base
from sqlalchemy import (
    Column, String, UUID, Text, Date, Integer, DECIMAL,
    TIMESTAMP, func, Enum, ForeignKey, Boolean, Numeric
)
from sqlalchemy.orm import relationship, foreign

# ---------------- USERS ----------------


class User(Base):
    __tablename__ = "users"

    id = Column(UUID, primary_key=True, index=True,
                default=func.gen_random_uuid())
    email = Column(String(255), unique=True, index=True, nullable=False)
    hashed_password = Column(String(255), nullable=False)
    role = Column(Enum("customer", "seller", "admin",
                  name="user_roles"), default="customer")
    
    # Email verification
    email_verified = Column(Boolean, default=False)
    email_verified_at = Column(TIMESTAMP, nullable=True)
    
    # Security fields
    failed_login_attempts = Column(Integer, default=0)
    locked_until = Column(TIMESTAMP, nullable=True)
    last_login = Column(TIMESTAMP, nullable=True)
    password_changed_at = Column(TIMESTAMP, server_default=func.current_timestamp())
    
    # Two-factor authentication (for future use)
    two_factor_enabled = Column(Boolean, default=False)
    two_factor_secret = Column(String(255), nullable=True)
    
    # Legacy field (keeping for backward compatibility)

    
    created_at = Column(TIMESTAMP, server_default=func.current_timestamp())
    updated_at = Column(TIMESTAMP, server_default=func.current_timestamp(
    ), onupdate=func.current_timestamp())

    # Relationships
    profile = relationship("Profile", back_populates="user", uselist=False)
    seller_profile = relationship(
        "SellerProfile", back_populates="user", uselist=False)
    notifications = relationship("Notification", back_populates="recipient", cascade="all, delete-orphan")
    notification_prefs = relationship("NotificationPreferences", back_populates="user", uselist=False, cascade="all, delete-orphan")
    inspections = relationship("GeneralInspection", back_populates="user")


# ---------------- PROFILES (CUSTOMERS) ----------------
class Profile(Base):
    __tablename__ = "profiles"

    id = Column(UUID, ForeignKey("users.id"), primary_key=True, index=True)
    name = Column(String(255), nullable=False)
    phone = Column(String(50), nullable=True)
    kyc_status = Column(Enum("pending", "approved", "rejected",
                        name="kyc_status"), default="pending")
    approval_date = Column(Date, nullable=True)
    avatar_url = Column(Text, nullable=True)
    bio = Column(Text, nullable=True)
    created_at = Column(TIMESTAMP, server_default=func.current_timestamp())
    updated_at = Column(TIMESTAMP, server_default=func.current_timestamp(
    ), onupdate=func.current_timestamp())

    # Relationships
    user = relationship("User", back_populates="profile")
    orders = relationship("Order", back_populates="buyer")
    payments = relationship("Payment", back_populates="buyer")
    addresses = relationship("Address", back_populates="user")
    reviews = relationship("Review", back_populates="user")
    wishlists = relationship("Wishlist", back_populates="user")
    stats = relationship("Stats", back_populates="user", uselist=False)
    agreements = relationship("GeneralAgreement", back_populates="user")
    asset_payments = relationship("GeneralPayment", back_populates="user")


# ---------------- SELLER PROFILES ----------------
class SellerProfile(Base):
    __tablename__ = "seller_profiles"

    id = Column(UUID, ForeignKey("users.id"), primary_key=True, index=True)
    business_name = Column(String(255), nullable=False)
    description = Column(Text, nullable=True)
    logo_url = Column(Text, nullable=True)
    contact_email = Column(String(255), nullable=True)
    contact_phone = Column(String(50), nullable=True)
    website_url = Column(Text, nullable=True)

    seller_type = Column(Enum("retailer", "car_dealer", "real_agent", "phone_dealer",
                             name="seller_type"), nullable=True)
    
    kyc_status = Column(Enum("pending", "approved", "rejected",
                        name="seller_kyc_status"), default="pending")
    approval_date = Column(Date, nullable=True)

    total_products = Column(Integer, default=0)
    total_orders = Column(Integer, default=0)
    total_revenue = Column(DECIMAL(12, 2), default=0)

    created_at = Column(TIMESTAMP, server_default=func.current_timestamp())
    updated_at = Column(TIMESTAMP, server_default=func.current_timestamp(
    ), onupdate=func.current_timestamp())

    # Payout and earnings tracking
    available_balance = Column(DECIMAL(12, 2), default=0)  # Available for payout
    pending_balance = Column(DECIMAL(12, 2), default=0)    # Pending from recent orders
    total_paid = Column(DECIMAL(12, 2), default=0)         # Total amount paid out
    payout_account_number = Column(String(20), nullable=True)
    payout_bank_code = Column(String(10), nullable=True)
    payout_bank_name = Column(String(100), nullable=True)  # Bank name for payouts
    payout_recipient_code = Column(String(100), nullable=True)  # Paystack recipient code
    
    # Relationships
    user = relationship("User", back_populates="seller_profile")
    products = relationship("Product", back_populates="seller")
    payments = relationship("Payment", back_populates="seller")
    payouts = relationship("SellerPayout", back_populates="seller")


# ---------------- CATEGORIES ----------------
class Category(Base):
    __tablename__ = "categories"

    id = Column(UUID, primary_key=True, index=True,
                default=func.gen_random_uuid())
    name = Column(String(100), unique=True, nullable=False)
    description = Column(Text, nullable=True)
    created_at = Column(TIMESTAMP, server_default=func.current_timestamp())

    # Relationships
    products = relationship("Product", back_populates="category")


# ---------------- PRODUCTS ----------------
class Product(Base):
    __tablename__ = "products"

    id = Column(UUID, primary_key=True, index=True,
                default=func.gen_random_uuid())
    seller_id = Column(UUID, ForeignKey("seller_profiles.id"), nullable=False)
    name = Column(String(255), nullable=False)
    description = Column(Text, nullable=True)
    price = Column(Numeric(15, 2), nullable=False)
    stock_quantity = Column(Integer, default=0)
    category_id = Column(UUID, ForeignKey("categories.id"), nullable=False)
    status = Column(Enum("active", "inactive", "out_of_stock",
                    name="product_status"), default="active")
    created_at = Column(TIMESTAMP, server_default=func.current_timestamp())
    updated_at = Column(TIMESTAMP, server_default=func.current_timestamp(
    ), onupdate=func.current_timestamp())

    # Relationships
    seller = relationship("SellerProfile", back_populates="products")
    category = relationship("Category", back_populates="products")
    # Order items should NOT be cascade deleted - they're part of financial records
    order_items = relationship("OrderItem", back_populates="product")
    # Reviews and wishlists can be cascade deleted since they become meaningless without the product
    reviews = relationship("Review", back_populates="product", cascade="all, delete-orphan")
    wishlists = relationship("Wishlist", back_populates="product", cascade="all, delete-orphan")
    images = relationship("AssetImage", back_populates="product", cascade="all, delete-orphan")


class AssetImage(Base):
    __tablename__ = "asset_images"

    id = Column(UUID, primary_key=True, index=True, default=func.gen_random_uuid())
    image_url = Column(Text, nullable=False)
    
    # Optional foreign keys for different asset types
    product_id = Column(UUID, ForeignKey("products.id", ondelete="CASCADE"), nullable=True)
    car_id = Column(UUID, ForeignKey("cars.id", ondelete="CASCADE"), nullable=True)
    property_id = Column(UUID, ForeignKey("properties.id", ondelete="CASCADE"), nullable=True)
    phone_id = Column(UUID, ForeignKey("phones.id", ondelete="CASCADE"), nullable=True)
    
    created_at = Column(TIMESTAMP, server_default=func.current_timestamp())

    # Relationships
    product = relationship("Product", back_populates="images")
    car = relationship("Car", back_populates="images")
    property = relationship("Property", back_populates="images")
    phone = relationship("Phone", back_populates="images")


# ---------------- ORDERS ----------------
class Order(Base):
    __tablename__ = "orders"

    id = Column(UUID, primary_key=True, index=True,
                default=func.gen_random_uuid())
    buyer_id = Column(UUID, ForeignKey("profiles.id"), nullable=False)
    total_amount = Column(Numeric(15, 2), nullable=False)
    status = Column(Enum("pending", "processing", "paid", "shipped", "delivered",
                    "cancelled", "partially_shipped", "partially_delivered", 
                    "partially_cancelled", name="order_status"), default="pending")
    delivery_address = Column(UUID, ForeignKey("addresses.id"), nullable=True)
    
    # Payment URL fields
    payment_url = Column(Text, nullable=True)  # Paystack authorization URL
    payment_reference = Column(String(100), nullable=True)  # Paystack reference
    payment_initialized_at = Column(TIMESTAMP, nullable=True)  # When payment was first initialized
    
    created_at = Column(TIMESTAMP, server_default=func.current_timestamp())
    updated_at = Column(TIMESTAMP, server_default=func.current_timestamp(
    ), onupdate=func.current_timestamp())

    # Relationships
    buyer = relationship("Profile", back_populates="orders")
    delivery_addr = relationship("Address", back_populates="orders")
    order_items = relationship(
        "OrderItem", back_populates="order", cascade="all, delete-orphan")
    payments = relationship("Payment", back_populates="order")


# ---------------- ORDER ITEMS ----------------
class OrderItem(Base):
    __tablename__ = "order_items"

    id = Column(UUID, primary_key=True, index=True,
                default=func.gen_random_uuid())
    order_id = Column(UUID, ForeignKey(
        "orders.id", ondelete="CASCADE"), nullable=False)
    product_id = Column(UUID, ForeignKey(
        "products.id", ondelete="CASCADE"), nullable=False)
    quantity = Column(Integer, nullable=False)
    price = Column(Numeric(15, 2), nullable=False)
    status = Column(Enum("pending", "processing", "paid", "shipped", "delivered", "cancelled", 
                        name="order_item_status"), default="pending", nullable=False)
    created_at = Column(TIMESTAMP, server_default=func.current_timestamp())
    updated_at = Column(TIMESTAMP, server_default=func.current_timestamp(
    ), onupdate=func.current_timestamp())

    # Relationships
    order = relationship("Order", back_populates="order_items")
    product = relationship("Product", back_populates="order_items")


# ---------------- PAYMENTS ----------------
class Payment(Base):
    __tablename__ = "payments"

    id = Column(UUID, primary_key=True, index=True,
                default=func.gen_random_uuid())
    order_id = Column(UUID, ForeignKey("orders.id"), nullable=False)
    buyer_id = Column(UUID, ForeignKey("profiles.id"), nullable=False)
    seller_id = Column(UUID, ForeignKey("seller_profiles.id"), nullable=True)
    amount = Column(DECIMAL(12, 2), nullable=False)

    status = Column(Enum("pending", "completed", "failed",
                    "refunded", name="payment_status"), default="pending")
    payment_method = Column(String(50), nullable=False)
    transaction_id = Column(String(100), unique=True, nullable=False)
    
    # Payment URL fields
    authorization_url = Column(Text, nullable=True)  # Paystack authorization URL
    access_code = Column(String(100), nullable=True)  # Paystack access code
    reference = Column(String(100), nullable=True)  # Paystack reference

    created_at = Column(TIMESTAMP, server_default=func.current_timestamp())
    updated_at = Column(TIMESTAMP, server_default=func.current_timestamp(
    ), onupdate=func.current_timestamp())

    # Relationships
    order = relationship("Order", back_populates="payments")
    buyer = relationship("Profile", back_populates="payments")
    seller = relationship("SellerProfile", back_populates="payments")


# ---------------- SELLER PAYOUTS ----------------
class SellerPayout(Base):
    __tablename__ = "seller_payouts"

    id = Column(UUID, primary_key=True, index=True, default=func.gen_random_uuid())
    seller_id = Column(UUID, ForeignKey("seller_profiles.id"), nullable=False, index=True)
    amount = Column(DECIMAL(12, 2), nullable=False)
    platform_fee = Column(DECIMAL(12, 2), default=0)  # Platform commission
    net_amount = Column(DECIMAL(12, 2), nullable=False)  # Amount after fees
    
    status = Column(Enum("pending", "processing", "completed", "failed", "cancelled",
                        name="payout_status"), default="pending")
    
    # Paystack transfer details
    transfer_reference = Column(String(100), nullable=True, unique=True)
    paystack_transfer_id = Column(String(100), nullable=True)
    recipient_code = Column(String(50), nullable=True)
    
    # Bank details used for payout
    account_number = Column(String(20), nullable=True)
    bank_code = Column(String(10), nullable=True)
    bank_name = Column(String(100), nullable=True)
    
    # Processing details
    processed_at = Column(TIMESTAMP, nullable=True)
    failure_reason = Column(Text, nullable=True)
    
    created_at = Column(TIMESTAMP, server_default=func.current_timestamp())
    updated_at = Column(TIMESTAMP, server_default=func.current_timestamp(),
                       onupdate=func.current_timestamp())
    
    # Relationships
    seller = relationship("SellerProfile", back_populates="payouts")


# ---------------- REVIEWS ----------------
class Review(Base):
    __tablename__ = "reviews"

    id = Column(UUID, primary_key=True, index=True,
                default=func.gen_random_uuid())
    product_id = Column(UUID, ForeignKey("products.id"), nullable=False)
    user_id = Column(UUID, ForeignKey("profiles.id"), nullable=False)
    # Should add CHECK constraint (1-5)
    rating = Column(Integer, nullable=False)
    comment = Column(Text, nullable=True)
    created_at = Column(TIMESTAMP, server_default=func.current_timestamp())
    updated_at = Column(TIMESTAMP, server_default=func.current_timestamp(
    ), onupdate=func.current_timestamp())

    # Relationships
    product = relationship("Product", back_populates="reviews")
    user = relationship("Profile", back_populates="reviews")


# ---------------- ADDRESSES ----------------
class Address(Base):
    __tablename__ = "addresses"

    id = Column(UUID, primary_key=True, index=True,
                default=func.gen_random_uuid())
    user_id = Column(UUID, ForeignKey("profiles.id"), nullable=False)
    title = Column(String(50), nullable=False)
    street_address = Column(String(255), nullable=False)
    city = Column(String(100), nullable=False)
    state_province = Column(String(100), nullable=False)
    postal_code = Column(String(20), nullable=False)
    country = Column(String(100), nullable=False)
    is_default = Column(Boolean, default=False)
    created_at = Column(TIMESTAMP, server_default=func.current_timestamp())
    updated_at = Column(TIMESTAMP, server_default=func.current_timestamp(
    ), onupdate=func.current_timestamp())

    # Relationships
    user = relationship("Profile", back_populates="addresses")
    orders = relationship("Order", back_populates="delivery_addr")


# ---------------- WISHLISTS ----------------
class Wishlist(Base):
    __tablename__ = "wishlists"

    id = Column(UUID, primary_key=True, index=True,
                default=func.gen_random_uuid())
    user_id = Column(UUID, ForeignKey("profiles.id"), nullable=False)
    product_id = Column(UUID, ForeignKey("products.id"), nullable=False)
    created_at = Column(TIMESTAMP, server_default=func.current_timestamp())
    updated_at = Column(TIMESTAMP, server_default=func.current_timestamp(
    ), onupdate=func.current_timestamp())

    # Relationships
    user = relationship("Profile", back_populates="wishlists")
    product = relationship("Product", back_populates="wishlists")


# ---------------- USER STATS ----------------
class Stats(Base):
    __tablename__ = "stats"

    id = Column(UUID, primary_key=True, index=True,
                default=func.gen_random_uuid())
    user_id = Column(UUID, ForeignKey("profiles.id"),
                     unique=True, nullable=False)
    total_buys = Column(Integer, default=0)
    total_sells = Column(Integer, default=0)
    created_at = Column(TIMESTAMP, server_default=func.current_timestamp())
    updated_at = Column(TIMESTAMP, server_default=func.current_timestamp(
    ), onupdate=func.current_timestamp())

    # Relationships
    user = relationship("Profile", back_populates="stats")


# ---------------- ADMIN STATS ----------------
class AdminStats(Base):
    __tablename__ = "admin_stats"

    id = Column(UUID, primary_key=True, index=True,
                default=func.gen_random_uuid())
    total_users = Column(Integer, default=0)
    total_products = Column(Integer, default=0)
    total_orders = Column(Integer, default=0)
    total_payments = Column(Integer, default=0)
    total_revenue = Column(DECIMAL(12, 2), default=0)
    created_at = Column(TIMESTAMP, server_default=func.current_timestamp())
    updated_at = Column(TIMESTAMP, server_default=func.current_timestamp(
    ), onupdate=func.current_timestamp())


# ---------------- NOTIFICATIONS ----------------
class Notification(Base):
    __tablename__ = "notifications"

    id = Column(UUID, primary_key=True, index=True, default=func.gen_random_uuid())
    user_id = Column(UUID, ForeignKey("users.id"), nullable=False, index=True)

    type = Column(Enum(
        "order_confirmed",
        "order_processing",
        "order_shipped",
        "order_delivered",
        "order_cancelled",
        "payment_successful",
        "payment_failed",
        "account_verified",
        "password_changed",
        "profile_updated",
        "wishlist_item_back_in_stock",
        "system_announcement",
        "promotional_offer",
        "car_approved",
        "car_rejected",
        "phone_approved",
        "phone_rejected",
        "inspection_scheduled",
        "inspection_confirmed",
        "property_acquired",
        "agreement_completed",
        "installment_paid",
        "payment_reminder",
        "installment_due",
        "installment_defaulted",
        name="notification_type"
    ), nullable=False)

    title = Column(String(255), nullable=False)
    message = Column(Text, nullable=False)

    priority = Column(Enum("low", "medium", "high", "urgent", name="notification_priority"), default="low")

    channels = Column(Text, nullable=False, default="in_app")  # comma-separated values

    data = Column(Text, nullable=True)  # JSON string

    is_read = Column(Boolean, default=False)
    is_sent = Column(Boolean, default=False)

    created_at = Column(TIMESTAMP, server_default=func.current_timestamp())
    read_at = Column(TIMESTAMP, nullable=True)
    sent_at = Column(TIMESTAMP, nullable=True)
    expires_at = Column(TIMESTAMP, nullable=True)

    # Relationships
    recipient = relationship("User", back_populates="notifications")


class NotificationPreferences(Base):
    __tablename__ = "notification_preferences"

    id = Column(UUID, primary_key=True, index=True, default=func.gen_random_uuid())
    user_id = Column(UUID, ForeignKey("users.id"), unique=True, nullable=False, index=True)

    # Email
    email_order_updates = Column(Boolean, default=True)
    email_payment_updates = Column(Boolean, default=True)
    email_account_updates = Column(Boolean, default=True)
    email_promotional_offers = Column(Boolean, default=False)
    email_system_announcements = Column(Boolean, default=True)

    # SMS
    sms_order_updates = Column(Boolean, default=False)
    sms_payment_updates = Column(Boolean, default=False)
    sms_account_updates = Column(Boolean, default=False)

    # Push
    push_order_updates = Column(Boolean, default=True)
    push_payment_updates = Column(Boolean, default=True)
    push_account_updates = Column(Boolean, default=True)
    push_promotional_offers = Column(Boolean, default=False)

    # In-app
    in_app_order_updates = Column(Boolean, default=True)
    in_app_payment_updates = Column(Boolean, default=True)
    in_app_account_updates = Column(Boolean, default=True)
    in_app_promotional_offers = Column(Boolean, default=True)
    in_app_system_announcements = Column(Boolean, default=True)

    created_at = Column(TIMESTAMP, server_default=func.current_timestamp())
    updated_at = Column(TIMESTAMP, server_default=func.current_timestamp(), onupdate=func.current_timestamp())

    # Relationships
    user = relationship("User", back_populates="notification_prefs")


# ---------------- AUTOMOTIVE ----------------

class Car(Base):
    __tablename__ = "cars"

    id = Column(UUID, primary_key=True, index=True, default=func.gen_random_uuid())
    seller_id = Column(UUID, ForeignKey("seller_profiles.id"), nullable=False)
    brand = Column(String(100), nullable=False)
    model = Column(String(100), nullable=False)
    year = Column(Integer, nullable=False)
    price = Column(Numeric(15, 2), nullable=False)
    min_deposit_percentage = Column(Numeric(5, 2), default=10)
    
    status = Column(Enum("available", "out_of_stock", name="car_listing_status"), default="available")
    
    created_at = Column(TIMESTAMP, server_default=func.current_timestamp())
    updated_at = Column(TIMESTAMP, server_default=func.current_timestamp(), onupdate=func.current_timestamp())

    # Relationships
    seller = relationship("SellerProfile")
    units = relationship("CarUnit", back_populates="car_listing", cascade="all, delete-orphan")
    images = relationship("AssetImage", back_populates="car", cascade="all, delete-orphan")
    inspections = relationship("GeneralInspection", primaryjoin="and_(Car.id==foreign(GeneralInspection.asset_id), GeneralInspection.asset_type=='automotive')", back_populates="car", cascade="all, delete-orphan")
    agreements = relationship("GeneralAgreement", primaryjoin="and_(Car.id==foreign(GeneralAgreement.asset_id), GeneralAgreement.asset_type=='automotive')", back_populates="car", cascade="all, delete-orphan")


class CarUnit(Base):
    __tablename__ = "car_units"

    id = Column(UUID, primary_key=True, index=True, default=func.gen_random_uuid())
    car_id = Column(UUID, ForeignKey("cars.id"), nullable=False)
    vin = Column(String(100), unique=True, nullable=False)
    mileage = Column(Integer, nullable=False)
    color = Column(String(50), nullable=True)
    status = Column(Enum("available", "inspected", "awaiting_payment", "sold", "reserved", 
                        name="unit_status"), default="available")
    
    created_at = Column(TIMESTAMP, server_default=func.current_timestamp())
    updated_at = Column(TIMESTAMP, server_default=func.current_timestamp(), onupdate=func.current_timestamp())

    # Relationships
    car_listing = relationship("Car", back_populates="units")




# ---------------- REAL ESTATE ----------------

class Property(Base):
    __tablename__ = "properties"

    id = Column(UUID, primary_key=True, index=True, default=func.gen_random_uuid())
    seller_id = Column(UUID, ForeignKey("seller_profiles.id"), nullable=False)
    title = Column(String(255), nullable=False)
    description = Column(Text, nullable=True)
    price = Column(Numeric(15, 2), nullable=False)
    location = Column(String(255), nullable=False)
    
    listing_type = Column(Enum("sale", "rental", "professional", name="listing_type"), default="sale")
    status = Column(Enum("available", "pending_inspection", "property_inspected", "awaiting_payment", 
                        "reserved", "sold", "rented", "under_financing", name="property_status"), default="available")
    
    created_at = Column(TIMESTAMP, server_default=func.current_timestamp())
    updated_at = Column(TIMESTAMP, server_default=func.current_timestamp(), onupdate=func.current_timestamp())

    # Relationships
    seller = relationship("SellerProfile")
    images = relationship("AssetImage", back_populates="property", cascade="all, delete-orphan")
    inspections = relationship("GeneralInspection", primaryjoin="and_(Property.id==foreign(GeneralInspection.asset_id), GeneralInspection.asset_type=='property')", back_populates="property", cascade="all, delete-orphan")
    agreements = relationship("GeneralAgreement", primaryjoin="and_(Property.id==foreign(GeneralAgreement.asset_id), GeneralAgreement.asset_type=='property')", back_populates="property", cascade="all, delete-orphan")


class RealEstateSessionRequest(Base):
    __tablename__ = "re_session_requests"

    id = Column(UUID, primary_key=True, index=True, default=func.gen_random_uuid())
    user_id = Column(UUID, ForeignKey("users.id"), nullable=False)
    location = Column(String(255), nullable=False)
    property_details = Column(Text, nullable=False)
    status = Column(Enum("pending", "pending_acquisition", "acquired", "declined", name="re_session_status"), default="pending")
    
    created_at = Column(TIMESTAMP, server_default=func.current_timestamp())
    updated_at = Column(TIMESTAMP, server_default=func.current_timestamp(), onupdate=func.current_timestamp())

    # Relationships
    user = relationship("User")


# ---------------- UNIFIED ASSET MODELS (NEW) ----------------

class GeneralInspection(Base):
    __tablename__ = "general_inspections"

    id = Column(UUID, primary_key=True, index=True, default=func.gen_random_uuid())
    seller_id = Column(UUID, ForeignKey("seller_profiles.id"), nullable=False)
    user_id = Column(UUID, ForeignKey("users.id"), nullable=False)
    
    asset_type = Column(Enum("automotive", "property", "phone", name="asset_category"), nullable=False)
    asset_id = Column(UUID, nullable=False) 
    unit_id = Column(UUID, nullable=True)
    
    inspection_date = Column(TIMESTAMP, nullable=False)
    notes = Column(Text, nullable=True)
    agreed_price = Column(Numeric(15, 2), nullable=True)
    
    status = Column(Enum("scheduled", "confirmed", "completed", "rejected", 
                        "agreement_pending", "agreement_accepted", 
                        name="gen_inspection_status"), default="scheduled")
    
    created_at = Column(TIMESTAMP, server_default=func.current_timestamp())
    updated_at = Column(TIMESTAMP, server_default=func.current_timestamp(), onupdate=func.current_timestamp())

    # Relationships
    seller = relationship("SellerProfile")
    user = relationship("User", back_populates="inspections")
    car = relationship("Car", primaryjoin="and_(foreign(GeneralInspection.asset_id)==Car.id, GeneralInspection.asset_type=='automotive')", back_populates="inspections", overlaps="inspections")
    property = relationship("Property", primaryjoin="and_(foreign(GeneralInspection.asset_id)==Property.id, GeneralInspection.asset_type=='property')", back_populates="inspections", overlaps="inspections")
    phone = relationship("Phone", primaryjoin="and_(foreign(GeneralInspection.asset_id)==Phone.id, GeneralInspection.asset_type=='phone')", back_populates="inspections", overlaps="inspections")


class GeneralAgreement(Base):
    __tablename__ = "general_agreements"

    id = Column(UUID, primary_key=True, index=True, default=func.gen_random_uuid())
    seller_id = Column(UUID, ForeignKey("seller_profiles.id"), nullable=False)
    user_id = Column(UUID, ForeignKey("profiles.id"), nullable=False)
    inspection_id = Column(UUID, ForeignKey("general_inspections.id"), nullable=True)
    
    asset_type = Column(Enum("automotive", "property", "phone", name="asset_category"), nullable=False)
    asset_id = Column(UUID, nullable=False)
    unit_id = Column(UUID, nullable=True)
    
    total_price = Column(Numeric(15, 2), nullable=False)
    deposit_paid = Column(Numeric(15, 2), nullable=True)
    remaining_balance = Column(Numeric(15, 2), nullable=True)
    
    plan_type = Column(Enum("structured", "flexible", name="financing_plan_type"), nullable=False)
    duration_months = Column(Integer, nullable=True)
    monthly_installment = Column(Numeric(15, 2), nullable=True)
    next_due_date = Column(TIMESTAMP, nullable=True)
    
    status = Column(Enum("pending_review", "pending_deposit", "active", "completed", "defaulted", "cancelled", 
                        name="gen_agreement_status"), default="pending_review")
    
    created_at = Column(TIMESTAMP, server_default=func.current_timestamp())
    updated_at = Column(TIMESTAMP, server_default=func.current_timestamp(), onupdate=func.current_timestamp())

    # Relationships
    seller = relationship("SellerProfile")
    user = relationship("Profile", back_populates="agreements")
    inspection = relationship("GeneralInspection")
    payments = relationship("GeneralPayment", back_populates="agreement")
    car = relationship("Car", primaryjoin="and_(foreign(GeneralAgreement.asset_id)==Car.id, GeneralAgreement.asset_type=='automotive')", back_populates="agreements", overlaps="agreements")
    property = relationship("Property", primaryjoin="and_(foreign(GeneralAgreement.asset_id)==Property.id, GeneralAgreement.asset_type=='property')", back_populates="agreements", overlaps="agreements")
    phone = relationship("Phone", primaryjoin="and_(foreign(GeneralAgreement.asset_id)==Phone.id, GeneralAgreement.asset_type=='phone')", back_populates="agreements", overlaps="agreements")


class GeneralPayment(Base):
    __tablename__ = "general_payments"

    id = Column(UUID, primary_key=True, index=True, default=func.gen_random_uuid())
    agreement_id = Column(UUID, ForeignKey("general_agreements.id"), nullable=False)
    user_id = Column(UUID, ForeignKey("profiles.id"), nullable=False)
    
    amount = Column(Numeric(15, 2), nullable=False)
    paystack_ref = Column(String(100), unique=True, nullable=False)
    payment_type = Column(Enum("deposit", "installment", "full_pay", name="asset_payment_type"), nullable=False)
    status = Column(Enum("success", "failed", "pending", name="asset_payment_status"), default="pending")
    
    created_at = Column(TIMESTAMP, server_default=func.current_timestamp())

    # Relationships
    agreement = relationship("GeneralAgreement", back_populates="payments")
    user = relationship("Profile", back_populates="asset_payments")


# ---------------- PHONES (NEW) ----------------

class Phone(Base):
    __tablename__ = "phones"

    id = Column(UUID, primary_key=True, index=True, default=func.gen_random_uuid())
    seller_id = Column(UUID, ForeignKey("seller_profiles.id"), nullable=False)
    brand = Column(String(100), nullable=False)
    model = Column(String(100), nullable=False)
    specs = Column(Text, nullable=True) # RAM, Storage, CPU etc.
    price = Column(Numeric(15, 2), nullable=False)
    min_deposit_percentage = Column(Numeric(5, 2), default=10)
    
    status = Column(Enum("available", "out_of_stock", name="phone_listing_status"), default="available")
    
    created_at = Column(TIMESTAMP, server_default=func.current_timestamp())
    updated_at = Column(TIMESTAMP, server_default=func.current_timestamp(), onupdate=func.current_timestamp())

    # Relationships
    seller = relationship("SellerProfile")
    units = relationship("PhoneUnit", back_populates="phone_listing", cascade="all, delete-orphan")
    inspections = relationship("GeneralInspection", primaryjoin="and_(Phone.id==foreign(GeneralInspection.asset_id), GeneralInspection.asset_type=='phone')", back_populates="phone", cascade="all, delete-orphan")
    agreements = relationship("GeneralAgreement", primaryjoin="and_(Phone.id==foreign(GeneralAgreement.asset_id), GeneralAgreement.asset_type=='phone')", back_populates="phone", cascade="all, delete-orphan")
    images = relationship("AssetImage", back_populates="phone", cascade="all, delete-orphan")


class PhoneUnit(Base):
    __tablename__ = "phone_units"

    id = Column(UUID, primary_key=True, index=True, default=func.gen_random_uuid())
    phone_id = Column(UUID, ForeignKey("phones.id"), nullable=False)
    imei = Column(String(100), unique=True, nullable=False)
    color = Column(String(50), nullable=True)
    grade = Column(String(20), nullable=True) # e.g. New, Open Box, Grade A
    battery_health = Column(Integer, nullable=True)
    
    status = Column(Enum("available", "inspected", "awaiting_payment", "sold", "reserved", 
                        name="phone_unit_status"), default="available")
    
    created_at = Column(TIMESTAMP, server_default=func.current_timestamp())
    updated_at = Column(TIMESTAMP, server_default=func.current_timestamp(), onupdate=func.current_timestamp())

    # Relationships
    phone_listing = relationship("Phone", back_populates="units")


# ---------------- AUDIT LOGS ----------------

class AuditLog(Base):
    __tablename__ = "audit_logs"

    id = Column(UUID, primary_key=True, index=True, default=func.gen_random_uuid())
    admin_id = Column(UUID, ForeignKey("users.id"), nullable=False)
    target_id = Column(UUID, nullable=True)
    action = Column(String(255), nullable=False)
    details = Column(Text, nullable=True)
    
    timestamp = Column(TIMESTAMP, server_default=func.current_timestamp())

    # Relationships
    admin = relationship("User")
