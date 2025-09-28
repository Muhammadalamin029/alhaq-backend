import logging
import traceback
import uuid
from fastapi.responses import JSONResponse
from fastapi.requests import Request
from fastapi import status
from fastapi.exceptions import RequestValidationError
from starlette.exceptions import HTTPException as StarletteHTTPException
from core.logging_config import get_logger, log_error

# Get logger for handlers
logger = get_logger("handlers")


def create_response(success: bool, message: str, data=None, code=status.HTTP_200_OK):
    return JSONResponse(
        status_code=code,
        content={
            "success": success,
            "message": message,
            "data": data if data is not None else []
        }
    )


async def http_exception_handler(request: Request, exc: StarletteHTTPException):
    """Handle HTTP exceptions with proper logging"""
    error_id = str(uuid.uuid4())
    
    # Extract request information
    method = request.method
    url = str(request.url)
    client_host = request.client.host if request.client else "unknown"
    
    # Log the HTTP exception
    log_error(
        logger,
        f"HTTP Exception: {exc.status_code} - {exc.detail}",
        extra={
            "error_id": error_id,
            "status_code": exc.status_code,
            "method": method,
            "url": url,
            "client_host": client_host,
            "exception_detail": exc.detail
        }
    )
    
    # Determine message
    message = exc.detail if isinstance(exc.detail, str) else "Error occurred"
    
    return create_response(
        success=False,
        message=message,
        data={"error_id": error_id} if exc.status_code >= 500 else None,
        code=exc.status_code,
    )


async def validation_exception_handler(request: Request, exc: RequestValidationError):
    """Handle validation exceptions with proper logging"""
    error_id = str(uuid.uuid4())
    
    # Extract request information
    method = request.method
    url = str(request.url)
    client_host = request.client.host if request.client else "unknown"
    
    # Log the validation error
    logger.warning(
        f"Validation Error: {len(exc.errors())} validation errors",
        extra={
            "error_id": error_id,
            "method": method,
            "url": url,
            "client_host": client_host,
            "validation_errors": exc.errors(),
            "error_count": len(exc.errors())
        }
    )
    
    return create_response(
        success=False,
        message="Validation error",
        data={"validation_errors": exc.errors(), "error_id": error_id},
        code=status.HTTP_422_UNPROCESSABLE_ENTITY,
    )


async def general_exception_handler(request: Request, exc: Exception):
    """Handle general exceptions with comprehensive logging"""
    error_id = str(uuid.uuid4())
    
    # Extract request information
    method = request.method
    url = str(request.url)
    client_host = request.client.host if request.client else "unknown"
    
    # Get request body if possible (for debugging)
    request_body = None
    try:
        if hasattr(request, '_body'):
            request_body = request._body.decode() if request._body else None
    except Exception:
        request_body = "<unable to read body>"
    
    # Log the general exception with full traceback
    logger.critical(
        f"Unhandled Exception: {type(exc).__name__}: {str(exc)}",
        exc_info=exc,
        extra={
            "error_id": error_id,
            "exception_type": type(exc).__name__,
            "exception_message": str(exc),
            "method": method,
            "url": url,
            "client_host": client_host,
            "request_body": request_body,
            "traceback": traceback.format_exc()
        }
    )
    
    # In production, don't expose internal error details
    return create_response(
        success=False,
        message="Internal server error",
        data={"error_id": error_id},
        code=status.HTTP_500_INTERNAL_SERVER_ERROR,
    )
