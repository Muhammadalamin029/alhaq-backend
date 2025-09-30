import os
from fastapi import FastAPI
from routers import (
    auth, products, categories, order,
    wishlist as wishlist_router,
    dashboard as dashboard_router,
    addresses as addresses_router,
    reviews as reviews_router,
    checkout as checkout_router,
    notifications as notifications_router,
    seller as seller_router,
    admin as admin_router,
)
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

# ------------------------------------------------------
# Logging setup
# ------------------------------------------------------
setup_logging(
    log_level=settings.LOG_LEVEL,
    log_to_file=settings.LOG_TO_FILE,
    log_to_console=settings.LOG_TO_CONSOLE,
    json_logs=settings.JSON_LOGS,
)
logger = get_logger("alhaq_backend")

# ------------------------------------------------------
# FastAPI app
# ------------------------------------------------------
app = FastAPI(title=settings.PROJECT_NAME)

# Middlewares
app.add_middleware(UserContextMiddleware)
app.add_middleware(LoggingMiddleware)

# Log startup
logger.info(f"Starting {settings.PROJECT_NAME} application", extra={
    "log_level": settings.LOG_LEVEL,
    "json_logs": settings.JSON_LOGS,
    "log_to_file": settings.LOG_TO_FILE,
})

# ------------------------------------------------------
# Database setup
# ------------------------------------------------------
try:
    Base.metadata.create_all(bind=engine)
    logger.info("Database tables created successfully")
except Exception as e:
    logger.error("Failed to create database tables", exc_info=e)

# ------------------------------------------------------
# CORS setup
# ------------------------------------------------------
origins = [
    "http://localhost:3000",                 # Local dev FE
    "https://alhaq-frontend.vercel.app",     # Production FE (no trailing slash!)
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ------------------------------------------------------
# Routers
# ------------------------------------------------------
logger.info("Registering API routes")
app.include_router(auth.router, prefix="/auth", tags=["Auth"])
app.include_router(products.router, prefix="/products", tags=["Products"])
app.include_router(categories.router, prefix="/categories", tags=["Categories"])
app.include_router(order.router, prefix="/orders", tags=["Orders"])
app.include_router(wishlist_router.router, prefix="/wishlist", tags=["Wishlist"])
app.include_router(dashboard_router.router, prefix="/dashboard", tags=["Dashboard"])
app.include_router(addresses_router.router, prefix="/addresses", tags=["Addresses"])
app.include_router(reviews_router.router, prefix="/reviews", tags=["Reviews"])
app.include_router(checkout_router.router, prefix="/checkout", tags=["Checkout"])
app.include_router(notifications_router.router, prefix="/notifications", tags=["Notifications"])
app.include_router(seller_router.router, prefix="/seller", tags=["Seller"])
app.include_router(admin_router.router, prefix="/admin", tags=["Admin"])

# ------------------------------------------------------
# Global exception handlers
# ------------------------------------------------------
logger.info("Registering global exception handlers")
app.add_exception_handler(StarletteHTTPException, http_exception_handler)
app.add_exception_handler(RequestValidationError, validation_exception_handler)
app.add_exception_handler(Exception, general_exception_handler)

# ------------------------------------------------------
# Health check
# ------------------------------------------------------
@app.get("/")
def health_check():
    logger.debug("Health check endpoint accessed")
    return {
        "status": "ok",
        "service": settings.PROJECT_NAME,
        "message": "Service is running"
    }

logger.info(f"{settings.PROJECT_NAME} application startup complete")
