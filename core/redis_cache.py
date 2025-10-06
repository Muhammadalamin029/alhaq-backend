import redis
import json
import hashlib
from typing import Optional, Any
from core.config import settings
import logging

logger = logging.getLogger(__name__)

class RedisCache:
    def __init__(self):
        self.redis_client = redis.from_url(
            settings.REDIS_URL,
            decode_responses=True,
            socket_connect_timeout=5,
            socket_timeout=5,
            retry_on_timeout=True,
            health_check_interval=30
        )
    
    def get(self, key: str) -> Optional[Any]:
        """Get value from cache"""
        try:
            value = self.redis_client.get(key)
            if value:
                return json.loads(value)
            return None
        except Exception as e:
            logger.error(f"Redis get error for key {key}: {e}")
            return None
    
    def set(self, key: str, value: Any, ttl: int = 300) -> bool:
        """Set value in cache with TTL"""
        try:
            serialized_value = json.dumps(value, default=str)
            return self.redis_client.setex(key, ttl, serialized_value)
        except Exception as e:
            logger.error(f"Redis set error for key {key}: {e}")
            return False
    
    def delete(self, key: str) -> bool:
        """Delete key from cache"""
        try:
            return bool(self.redis_client.delete(key))
        except Exception as e:
            logger.error(f"Redis delete error for key {key}: {e}")
            return False
    
    def delete_pattern(self, pattern: str) -> int:
        """Delete all keys matching pattern"""
        try:
            keys = self.redis_client.keys(pattern)
            if keys:
                return self.redis_client.delete(*keys)
            return 0
        except Exception as e:
            logger.error(f"Redis delete pattern error for {pattern}: {e}")
            return 0
    
    def create_key(self, prefix: str, *args) -> str:
        """Create a cache key from prefix and arguments"""
        key_data = f"{prefix}:{':'.join(str(arg) for arg in args)}"
        return hashlib.md5(key_data.encode()).hexdigest()
    
    def health_check(self) -> bool:
        """Check if Redis is healthy"""
        try:
            return self.redis_client.ping()
        except Exception as e:
            logger.error(f"Redis health check failed: {e}")
            return False

# Global cache instance
cache = RedisCache()
