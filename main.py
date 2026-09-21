from fastapi import FastAPI
from routers import (
    auth,
    products,
    categories,
    order,
    wishlist as wishlist_router,
    dashboard as dashboard_router,
    addresses as addresses_router,
    reviews as reviews_router,
    checkout as checkout_router,
    notifications as notifications_router,
    admin as admin_router,
    payments,
    automotive,
    assets,
    properties,
    disputes,
    system_settings,
    public as public_router,
    legal_documents as legal_documents_router,
    financing as financing_router,
    delivery as delivery_router,
    seo as seo_router,
)
from core.config import settings
from db.session import engine
from core.model import Base
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.routing import Match
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
    log_to_console=settings.LOG_TO_CONSOLE,
)
logger = get_logger("lel_store_backend")

# ------------------------------------------------------
# FastAPI app
# ------------------------------------------------------
app = FastAPI(
    title=settings.PROJECT_NAME,
    # Resolve trailing-slash variants centrally without issuing 307 redirects.
    redirect_slashes=False,
)

# Middlewares
app.add_middleware(UserContextMiddleware)
app.add_middleware(LoggingMiddleware)

# Log startup
logger.info(
    f"Starting {settings.PROJECT_NAME} application",
    extra={
        "log_level": settings.LOG_LEVEL,
        "log_to_console": settings.LOG_TO_CONSOLE,
    },
)

# ------------------------------------------------------
# Database setup
# ------------------------------------------------------
logger.info("Database schema managed by Alembic")

# Add CORS middleware with more permissive settings for development
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.ALLOWED_ORIGINS,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "DELETE", "PATCH", "OPTIONS"],
    allow_headers=["*"],
    expose_headers=["*"],
)


# Add CORS debugging middleware
@app.middleware("http")
async def cors_debug_middleware(request, call_next):
    # Log CORS-related headers
    origin = request.headers.get("origin")
    method = request.method

    logger.info(
        f"CORS Debug - Origin: {origin}, Method: {method}, Path: {request.url.path}"
    )

    response = await call_next(request)

    # Add CORS headers to response for debugging
    if origin and origin in settings.ALLOWED_ORIGINS:
        response.headers["Access-Control-Allow-Origin"] = origin
        response.headers["Access-Control-Allow-Credentials"] = "true"

    return response


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
app.include_router(
    notifications_router.router, prefix="/notifications", tags=["Notifications"]
)
app.include_router(admin_router.router, prefix="/admin", tags=["Admin"])
app.include_router(payments.router, prefix="/payments", tags=["Payments"])
app.include_router(automotive.router, prefix="/automotive", tags=["Automotive"])
app.include_router(assets.router, prefix="/assets", tags=["Assets"])
app.include_router(properties.router, prefix="/properties", tags=["Properties"])
app.include_router(disputes.router, prefix="/disputes", tags=["Disputes"])
app.include_router(
    system_settings.router, prefix="/system-settings", tags=["System Settings"]
)
app.include_router(public_router.router, prefix="/public", tags=["Public"])
app.include_router(
    legal_documents_router.public_router, prefix="/public", tags=["Public"]
)
app.include_router(legal_documents_router.admin_router, prefix="/admin", tags=["Admin"])
app.include_router(financing_router.router, prefix="/financing", tags=["Financing"])
app.include_router(
    financing_router.admin_router, prefix="/admin/financing", tags=["Admin"]
)
app.include_router(delivery_router.router, prefix="/admin/delivery", tags=["Admin"])
app.include_router(seo_router.router, tags=["SEO"])

# ------------------------------------------------------
# Trailing-slash compatibility
# ------------------------------------------------------
@app.middleware("http")
async def trailing_slash_compatibility_middleware(request, call_next):
    """Resolve /route and /route/ to the same registered route without redirects."""
    path = request.scope.get("path", "")

    if path not in ("", "/"):

        def route_matches(candidate_path: str) -> bool:
            scope = dict(request.scope)
            scope["path"] = candidate_path
            scope["raw_path"] = candidate_path.encode("utf-8")

            for registered_route in app.router.routes:
                match, _ = registered_route.matches(scope)
                if match is Match.FULL:
                    return True

            return False

        if not route_matches(path):
            alternate_path = (
                path.rstrip("/") if path.endswith("/") else f"{path}/"
            )

            if route_matches(alternate_path):
                request.scope["path"] = alternate_path
                request.scope["raw_path"] = alternate_path.encode("utf-8")

    return await call_next(request)


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
@app.head("/")
def health_check():
    logger.debug("Health check endpoint accessed")
    return {
        "status": "ok",
        "service": settings.PROJECT_NAME,
        "message": "Service is running",
    }


logger.info(f"{settings.PROJECT_NAME} application startup complete")
