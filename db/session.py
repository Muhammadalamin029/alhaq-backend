from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, declarative_base
from core.config import settings

Base = declarative_base()

# Preload all models to avoid first-query overhead
def _preload_models():
    """Preload all models to avoid first-query overhead"""
    try:
        from core.model import User, Profile, Product, Category, Order, OrderItem, Payment, Review, Wishlist, Address, Stats, Notification, StoreProfile
        # This forces SQLAlchemy to load all model metadata
        Base.metadata.tables
    except ImportError:
        pass  # Models not available yet

# Preload models
_preload_models()


def _normalize_db_url(url: str) -> str:
    # Heroku-style scheme that SQLAlchemy can't parse; psycopg v3 URLs
    # (postgresql+psycopg://) work as-is since psycopg[binary] is installed.
    if url.startswith("postgres://"):
        return url.replace("postgres://", "postgresql://", 1)
    return url


engine = create_engine(
    _normalize_db_url(settings.DATABASE_URL),
    echo=False,  # Disable SQL logging in production
    future=True,
    # Small pool: the DB is Neon (serverless, strict connection caps) behind
    # its own pooler, and API + worker + beat each hold a pool. Bunched
    # traffic queues briefly instead of exhausting database connections.
    pool_size=5,
    max_overflow=10,
    pool_pre_ping=True,  # Verify connections before use
    pool_recycle=3600,  # Recycle connections every hour
    # Performance optimizations
    pool_timeout=30,  # Connection timeout
    pool_reset_on_return='rollback'  # Never commit stray partial work
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
        # Read-only fast path: release without committing anything, so a
        # route that forgot its commit can't leak writes into the pool.
        db.rollback()
    except Exception:
        # Never let a failed transaction return to the pool half-applied.
        db.rollback()
        raise
    finally:
        db.close()
