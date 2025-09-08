from db.session import Base
from sqlalchemy import (
    Column, String, UUID, Text, Date, Integer, DECIMAL,
    TIMESTAMP, func, Enum, ForeignKey, Boolean
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
    verified = Column(Boolean, default=False)
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
    checkouts = relationship("Checkout", back_populates="buyer")
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

    # Relationships
    user = relationship("User", back_populates="seller_profile")
    products = relationship("Product", back_populates="seller")
    payments = relationship("Payment", back_populates="seller")


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
    image_url = Column(Text, nullable=True)
    price = Column(DECIMAL(10, 2), nullable=False)
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
    order_items = relationship("OrderItem", back_populates="product")
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
    is_primary = Column(Boolean, default=False)
    created_at = Column(TIMESTAMP, server_default=func.current_timestamp())

    # Relationships
    product = relationship("Product", back_populates="images")


# ---------------- ORDERS ----------------
class Order(Base):
    __tablename__ = "orders"

    id = Column(UUID, primary_key=True, index=True,
                default=func.gen_random_uuid())
    buyer_id = Column(UUID, ForeignKey("profiles.id"), nullable=False)
    total_amount = Column(DECIMAL(10, 2), nullable=False)
    status = Column(Enum("pending", "processing", "shipped", "delivered",
                    "cancelled", name="order_status"), default="pending")
    delivery_address = Column(UUID, ForeignKey("addresses.id"), nullable=True)
    created_at = Column(TIMESTAMP, server_default=func.current_timestamp())
    updated_at = Column(TIMESTAMP, server_default=func.current_timestamp(
    ), onupdate=func.current_timestamp())

    # Relationships
    buyer = relationship("Profile", back_populates="orders")
    delivery_addr = relationship("Address", back_populates="orders")
    order_items = relationship("OrderItem", back_populates="order")
    payments = relationship("Payment", back_populates="order")
    checkouts = relationship("Checkout", back_populates="order")


# ---------------- ORDER ITEMS ----------------
class OrderItem(Base):
    __tablename__ = "order_items"

    id = Column(UUID, primary_key=True, index=True,
                default=func.gen_random_uuid())
    order_id = Column(UUID, ForeignKey("orders.id"), nullable=False)
    product_id = Column(UUID, ForeignKey("products.id"), nullable=False)
    quantity = Column(Integer, nullable=False)
    price = Column(DECIMAL(10, 2), nullable=False)
    created_at = Column(TIMESTAMP, server_default=func.current_timestamp())
    updated_at = Column(TIMESTAMP, server_default=func.current_timestamp(
    ), onupdate=func.current_timestamp())

    # Relationships
    order = relationship("Order", back_populates="order_items")
    product = relationship("Product", back_populates="order_items")


# ---------------- CHECKOUTS ----------------
class Checkout(Base):
    __tablename__ = "checkouts"

    id = Column(UUID, primary_key=True, index=True,
                default=func.gen_random_uuid())
    buyer_id = Column(UUID, ForeignKey("profiles.id"), nullable=False)
    order_id = Column(UUID, ForeignKey("orders.id"), nullable=False)
    total_amount = Column(DECIMAL(12, 2), nullable=False)

    status = Column(Enum("initiated", "awaiting_payment", "completed",
                    "cancelled", name="checkout_status"), default="initiated")
    payment_reference = Column(String(100), unique=True, nullable=True)
    expires_at = Column(TIMESTAMP, nullable=True)

    created_at = Column(TIMESTAMP, server_default=func.current_timestamp())
    updated_at = Column(TIMESTAMP, server_default=func.current_timestamp(
    ), onupdate=func.current_timestamp())

    # Relationships
    buyer = relationship("Profile", back_populates="checkouts")
    order = relationship("Order", back_populates="checkouts")


# ---------------- PAYMENTS ----------------
class Payment(Base):
    __tablename__ = "payments"

    id = Column(UUID, primary_key=True, index=True,
                default=func.gen_random_uuid())
    order_id = Column(UUID, ForeignKey("orders.id"), nullable=False)
    buyer_id = Column(UUID, ForeignKey("profiles.id"), nullable=False)
    seller_id = Column(UUID, ForeignKey("seller_profiles.id"), nullable=False)
    amount = Column(DECIMAL(12, 2), nullable=False)

    status = Column(Enum("pending", "completed", "failed",
                    "refunded", name="payment_status"), default="pending")
    payment_method = Column(String(50), nullable=False)
    transaction_id = Column(String(100), unique=True, nullable=False)

    created_at = Column(TIMESTAMP, server_default=func.current_timestamp())
    updated_at = Column(TIMESTAMP, server_default=func.current_timestamp(
    ), onupdate=func.current_timestamp())

    # Relationships
    order = relationship("Order", back_populates="payments")
    buyer = relationship("Profile", back_populates="payments")
    seller = relationship("SellerProfile", back_populates="payments")


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
