from fastapi import Request, Response
from starlette.middleware.base import BaseHTTPMiddleware
from typing import Callable
import time
import json
from core.redis_cache import cache
import logging

logger = logging.getLogger(__name__)

class RedisCacheMiddleware(BaseHTTPMiddleware):
    def __init__(self, app, cache_ttl: int = 300, cache_prefix: str = "api"):
        super().__init__(app)
        self.cache_ttl = cache_ttl
        self.cache_prefix = cache_prefix
    
    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        # Only cache GET requests
        if request.method != "GET":
            return await call_next(request)
        
        # Skip cache for certain endpoints
        skip_paths = ["/auth", "/admin", "/notifications"]
        if any(request.url.path.startswith(path) for path in skip_paths):
            return await call_next(request)
        
        # Create cache key
        cache_key = self._create_cache_key(request)
        
        # Try to get from cache
        cached_response = cache.get(cache_key)
        if cached_response:
            logger.debug(f"Cache hit for {request.url.path}")
            return Response(
                content=cached_response["content"],
                status_code=cached_response["status_code"],
                headers=cached_response["headers"],
                media_type=cached_response["media_type"]
            )
        
        # Process request
        start_time = time.time()
        response = await call_next(request)
        process_time = time.time() - start_time
        
        # Cache successful responses
        if response.status_code == 200:
            response_body = b""
            async for chunk in response.body_iterator:
                response_body += chunk
            
            # Prepare cache data
            cache_data = {
                "content": response_body.decode(),
                "status_code": response.status_code,
                "headers": dict(response.headers),
                "media_type": response.media_type
            }
            
            # Store in cache
            cache.set(cache_key, cache_data, self.cache_ttl)
            logger.debug(f"Cache stored for {request.url.path} (took {process_time:.3f}s)")
            
            return Response(
                content=response_body,
                status_code=response.status_code,
                headers=response.headers,
                media_type=response.media_type
            )
        
        logger.debug(f"Request processed in {process_time:.3f}s (not cached)")
        return response
    
    def _create_cache_key(self, request: Request) -> str:
        """Create a unique cache key for the request"""
        # Include path, query params, and headers that affect response
        key_data = f"{request.url.path}?{request.url.query}"
        
        # Include user-specific headers if present
        user_id = request.headers.get("x-user-id")
        if user_id:
            key_data += f":user:{user_id}"
        
        return cache.create_key(self.cache_prefix, key_data)
