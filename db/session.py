from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, declarative_base
from core.config import settings

Base = declarative_base()

# Preload all models to avoid first-query overhead
def _preload_models():
    """Preload all models to avoid first-query overhead"""
    try:
        from core.model import User, Profile, SellerProfile, Product, Category, Order, OrderItem, Payment, Review, Wishlist, Address, Stats, Notification, SellerPayout
        # This forces SQLAlchemy to load all model metadata
        Base.metadata.tables
    except ImportError:
        pass  # Models not available yet

# Preload models
_preload_models()

engine = create_engine(
    settings.DATABASE_URL,
    echo=False,  # Disable SQL logging in production
    future=True,
    pool_size=20,  # Increase connection pool
    max_overflow=30,  # Allow more connections
    pool_pre_ping=True,  # Verify connections before use
    pool_recycle=3600,  # Recycle connections every hour
    # Performance optimizations
    pool_timeout=30,  # Connection timeout
    pool_reset_on_return='commit'  # Reset connections on return
)

SessionLocal = sessionmaker(
    autocommit=False,
    autoflush=False,
    bind=engine,
    future=True
)


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
