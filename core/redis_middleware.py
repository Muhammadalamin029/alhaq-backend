from fastapi import Request, Response
from starlette.middleware.base import BaseHTTPMiddleware
from typing import Callable, Dict, Any
import time
import json
import hashlib
from core.redis_cache import RedisCache
import logging

logger = logging.getLogger(__name__)

# Simple in-memory cache fallback
class InMemoryCache:
    def __init__(self):
        self._cache: Dict[str, Dict[str, Any]] = {}
    
    def get(self, key: str) -> Any:
        if key in self._cache:
            entry = self._cache[key]
            if time.time() < entry['expires']:
                return entry['data']
            else:
                del self._cache[key]
        return None
    
    def set(self, key: str, value: Any, ttl: int = 300):
        self._cache[key] = {
            'data': value,
            'expires': time.time() + ttl
        }
    
    def delete(self, pattern: str):
        keys_to_delete = [key for key in self._cache.keys() if pattern.replace('*', '') in key]
        for key in keys_to_delete:
            del self._cache[key]

# Fallback cache instance
fallback_cache = InMemoryCache()

class RedisCacheMiddleware(BaseHTTPMiddleware):
    def __init__(self, app, cache_ttl: int = 300, cache_prefix: str = "api"):
        super().__init__(app)
        self.cache_ttl = cache_ttl
        self.cache_prefix = cache_prefix
    
    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        # Handle non-GET requests (invalidate cache)
        if request.method != "GET":
            # Process the request first
            response = await call_next(request)
            
            # If the request was successful, invalidate related cache
            if response.status_code in [200, 201, 204]:
                await self._invalidate_related_cache(request)
            
            return response
        
        # Skip cache for certain endpoints
        skip_paths = ["/auth", "/admin", "/notifications", "/docs", "/openapi.json"]
        if any(request.url.path.startswith(path) for path in skip_paths):
            return await call_next(request)
        
        # Create cache key
        cache_key = self._create_cache_key(request)
        
        # Try to get from cache (Redis first, then fallback)
        cached_response = None
        try:
            cached_response = await RedisCache.get(cache_key)
        except Exception as e:
            logger.warning(f"Redis cache get failed for {request.url.path}: {e}")
            # Try fallback cache
            try:
                cached_response = fallback_cache.get(cache_key)
            except Exception as fallback_e:
                logger.warning(f"Fallback cache get failed for {request.url.path}: {fallback_e}")
        
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
            
            # Store in cache (Redis first, then fallback)
            try:
                await RedisCache.set(cache_key, cache_data, self.cache_ttl)
                logger.debug(f"Redis cache stored for {request.url.path} (took {process_time:.3f}s)")
            except Exception as e:
                logger.warning(f"Redis cache set failed for {request.url.path}: {e}")
                # Try fallback cache
                try:
                    fallback_cache.set(cache_key, cache_data, self.cache_ttl)
                    logger.debug(f"Fallback cache stored for {request.url.path} (took {process_time:.3f}s)")
                except Exception as fallback_e:
                    logger.warning(f"Fallback cache set failed for {request.url.path}: {fallback_e}")
            
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
        
        # Create a hash for shorter keys
        key_hash = hashlib.md5(key_data.encode()).hexdigest()
        return f"{self.cache_prefix}:{key_hash}"
    
    async def _invalidate_related_cache(self, request: Request):
        """Invalidate cache based on the request path"""
        try:
            path = request.url.path
            
            # Define cache invalidation patterns based on path
            patterns_to_clear = []
            
            if path.startswith("/categories"):
                patterns_to_clear = ["api:*categories*"]
                logger.info(f"Invalidating categories cache for {request.method} {path}")
                
            elif path.startswith("/products"):
                patterns_to_clear = ["api:*products*"]
                logger.info(f"Invalidating products cache for {request.method} {path}")
                
            elif path.startswith("/orders"):
                patterns_to_clear = ["api:*orders*"]
                logger.info(f"Invalidating orders cache for {request.method} {path}")
                
            elif path.startswith("/payments"):
                patterns_to_clear = ["api:*payments*"]
                logger.info(f"Invalidating payments cache for {request.method} {path}")
                
            elif path.startswith("/users") or path.startswith("/sellers"):
                patterns_to_clear = ["api:*users*", "api:*sellers*"]
                logger.info(f"Invalidating user/seller cache for {request.method} {path}")
                
            else:
                patterns_to_clear = ["api:*"]
                logger.info(f"Invalidating all cache for {request.method} {path}")
            
            # Clear Redis cache
            for pattern in patterns_to_clear:
                try:
                    await RedisCache.clear_pattern(pattern)
                except Exception as redis_e:
                    logger.warning(f"Redis cache clear failed for pattern {pattern}: {redis_e}")
            
            # Clear fallback cache
            for pattern in patterns_to_clear:
                try:
                    fallback_cache.delete(pattern)
                except Exception as fallback_e:
                    logger.warning(f"Fallback cache clear failed for pattern {pattern}: {fallback_e}")
                
        except Exception as e:
            logger.warning(f"Failed to invalidate cache for {request.method} {request.url.path}: {e}")
