from db.session import Base
from sqlalchemy import (
    Column, String, UUID, Text, Date, Integer, DECIMAL,
    TIMESTAMP, func, Enum, ForeignKey, Boolean, Numeric
)
from sqlalchemy.orm import relationship

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


# ---------------- PROFILES (CUSTOMERS) ----------------
class Profile(Base):
    __tablename__ = "profiles"

    id = Column(UUID, ForeignKey("users.id"), primary_key=True, index=True)
    name = Column(String(255), nullable=False)
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
    payout_recipient_code = Column(String(50), nullable=True)  # Paystack recipient code
    
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
    order_items = relationship(
        "OrderItem", back_populates="product", cascade="all, delete-orphan")
    reviews = relationship("Review", back_populates="product")
    wishlists = relationship("Wishlist", back_populates="product")
    images = relationship("ProductImage", back_populates="product")


# ---------------- PRODUCT IMAGES ----------------
class ProductImage(Base):
    __tablename__ = "product_images"

    id = Column(UUID, primary_key=True, index=True,
                default=func.gen_random_uuid())
    product_id = Column(UUID, ForeignKey("products.id"), nullable=False)
    image_url = Column(Text, nullable=False)
    created_at = Column(TIMESTAMP, server_default=func.current_timestamp())

    # Relationships
    product = relationship("Product", back_populates="images")


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
    user_id = Column(UUID, nullable=False, index=True)  # References either profiles.id or seller_profiles.id

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


class NotificationPreferences(Base):
    __tablename__ = "notification_preferences"

    id = Column(UUID, primary_key=True, index=True, default=func.gen_random_uuid())
    user_id = Column(UUID, ForeignKey("profiles.id"), unique=True, nullable=False, index=True)

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
