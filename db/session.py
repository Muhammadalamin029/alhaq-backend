from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, declarative_base
from core.config import settings

Base = declarative_base()

engine = create_engine(
    settings.DATABASE_URL,
    echo=False,  # Disable SQL logging in production
    future=True,
    pool_size=20,  # Increase connection pool
    max_overflow=30,  # Allow more connections
    pool_pre_ping=True,  # Verify connections before use
    pool_recycle=3600,  # Recycle connections every hour
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
