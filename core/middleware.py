import time
import uuid
from typing import Callable
from fastapi import Request, Response
from starlette.middleware.base import BaseHTTPMiddleware
from core.logging_config import get_logger, log_api_request

# Get logger for middleware
logger = get_logger("middleware")


class LoggingMiddleware(BaseHTTPMiddleware):
    """Middleware to log all API requests and responses"""
    
    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        # Generate request ID
        request_id = str(uuid.uuid4())
        
        # Add request ID to request state for use in other parts of the app
        request.state.request_id = request_id
        
        # Record start time
        start_time = time.time()
        
        # Extract request information
        method = request.method
        url = str(request.url)
        path = request.url.path
        client_host = request.client.host if request.client else "unknown"
        user_agent = request.headers.get("user-agent", "")
        
        # Log request start
        logger.info(
            f"Request started: {method} {path}",
            extra={
                "request_id": request_id,
                "method": method,
                "url": url,
                "path": path,
                "client_host": client_host,
                "user_agent": user_agent,
                "event": "request_start"
            }
        )
        
        try:
            # Process the request
            response = await call_next(request)
            
            # Calculate duration
            duration_ms = (time.time() - start_time) * 1000
            
            # Log successful response
            log_api_request(
                logger=logger,
                method=method,
                endpoint=path,
                status_code=response.status_code,
                duration_ms=duration_ms,
                user_id=getattr(request.state, 'user_id', None),
                request_id=request_id,
                client_host=client_host
            )
            
            # Add request ID to response headers for debugging
            response.headers["X-Request-ID"] = request_id
            
            return response
            
        except Exception as e:
            # Calculate duration even for errors
            duration_ms = (time.time() - start_time) * 1000
            
            # Log error
            logger.error(
                f"Request failed: {method} {path} - {type(e).__name__}: {str(e)}",
                exc_info=e,
                extra={
                    "request_id": request_id,
                    "method": method,
                    "path": path,
                    "client_host": client_host,
                    "duration": duration_ms,
                    "exception_type": type(e).__name__,
                    "exception_message": str(e),
                    "event": "request_error"
                }
            )
            
            # Re-raise the exception to be handled by exception handlers
            raise


class UserContextMiddleware(BaseHTTPMiddleware):
    """Middleware to add user context to requests for logging"""
    
    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        # Try to extract user information from JWT token for logging context
        user_id = None
        user_email = None
        
        try:
            from core.auth import decode_token
            from core.config import settings
            
            # Get authorization header
            auth_header = request.headers.get("authorization")
            
            if auth_header and auth_header.startswith("Bearer "):
                token = auth_header.split(" ")[1]
                try:
                    payload = decode_token(token, settings.SECRET_KEY)
                    user_id = payload.get("sub")
                    
                    # Store user context in request state for logging
                    request.state.user_id = user_id
                    
                except Exception:
                    # Token invalid or expired, ignore for middleware logging
                    pass
                    
        except Exception:
            # Any error in user context extraction should not break the request
            pass
        
        # Continue with request processing
        response = await call_next(request)
        return response