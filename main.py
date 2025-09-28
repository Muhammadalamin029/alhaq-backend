import os
from fastapi import FastAPI
from routers import auth, products, categories, order
from routers import wishlist as wishlist_router
from routers import dashboard as dashboard_router
from routers import addresses as addresses_router
from routers import reviews as reviews_router
# Profile router removed - functionality consolidated into auth router
from routers import checkout as checkout_router
from routers import notifications as notifications_router
from routers import seller as seller_router
from routers import admin as admin_router
from core.config import settings
from db.session import engine
from core.model import Base
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from starlette.exceptions import HTTPException as StarletteHTTPException
from core.handlers import (
    http_exception_handler,
    validation_exception_handler,
    general_exception_handler,
)
from core.logging_config import setup_logging, get_logger
from core.middleware import LoggingMiddleware, UserContextMiddleware

# Initialize logging system
setup_logging(
    log_level=settings.LOG_LEVEL,
    log_to_file=settings.LOG_TO_FILE,
    log_to_console=settings.LOG_TO_CONSOLE,
    json_logs=settings.JSON_LOGS
)

# Get main app logger
logger = get_logger("alhaq_backend")

# Create FastAPI app
app = FastAPI(title=settings.PROJECT_NAME)

# Add middlewares
app.add_middleware(UserContextMiddleware)
app.add_middleware(LoggingMiddleware)

# Log application startup
logger.info(f"Starting {settings.PROJECT_NAME} application", extra={
    "log_level": settings.LOG_LEVEL,
    "json_logs": settings.JSON_LOGS,
    "log_to_file": settings.LOG_TO_FILE
})

# Create database tables
try:
    Base.metadata.create_all(bind=engine)
    logger.info("Database tables created successfully")
except Exception as e:
    logger.error("Failed to create database tables", exc_info=e)

# Add CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],        # List of allowed origins
    allow_credentials=True,       # Cookies, Authorization headers
    allow_methods=["*"],          # GET, POST, PUT, DELETE, etc.
    allow_headers=["*"],          # All headers
)

# Register routers
logger.info("Registering API routes")
app.include_router(auth.router, prefix="/auth", tags=["Auth"])
logger.debug("Registered auth routes at /auth")
app.include_router(products.router, prefix="/products", tags=["Products"])
logger.debug("Registered products routes at /products")
app.include_router(categories.router, prefix="/categories", tags=["Categories"])
logger.debug("Registered categories routes at /categories")
app.include_router(order.router, prefix="/orders", tags=["Orders"])
logger.debug("Registered order routes at /orders")
app.include_router(wishlist_router.router, prefix="/wishlist", tags=["Wishlist"])
logger.debug("Registered wishlist routes at /wishlist")
app.include_router(dashboard_router.router, prefix="/dashboard", tags=["Dashboard"])
logger.debug("Registered dashboard routes at /dashboard")
app.include_router(addresses_router.router, prefix="/addresses", tags=["Addresses"])
logger.debug("Registered addresses routes at /addresses")
app.include_router(reviews_router.router, prefix="/reviews", tags=["Reviews"])
logger.debug("Registered reviews routes at /reviews")
# Profile routes consolidated into /auth - no separate /profile endpoint needed
app.include_router(checkout_router.router, prefix="/checkout", tags=["Checkout"])
logger.debug("Registered checkout routes at /checkout")
app.include_router(notifications_router.router, prefix="/notifications", tags=["Notifications"])
logger.debug("Registered notifications routes at /notifications")
app.include_router(seller_router.router, prefix="/seller", tags=["Seller"])
logger.debug("Registered seller routes at /seller")
app.include_router(admin_router.router, prefix="/admin", tags=["Admin"])
logger.debug("Registered admin routes at /admin")

# Register global exception handlers
logger.info("Registering global exception handlers")
app.add_exception_handler(StarletteHTTPException, http_exception_handler)
app.add_exception_handler(RequestValidationError, validation_exception_handler)
app.add_exception_handler(Exception, general_exception_handler)
logger.debug("Exception handlers registered successfully")


@app.get("/")
def health_check():
    """Health check endpoint"""
    logger.debug("Health check endpoint accessed")
    return {
        "status": "ok",
        "service": settings.PROJECT_NAME,
        "message": "Service is running"
    }


logger.info(f"{settings.PROJECT_NAME} application startup complete")
