import json
import asyncio
from typing import Optional, Any
from urllib.parse import urlparse

import redis.asyncio as aioredis
from redis.asyncio import Redis
from core.config import settings
from core.logging_config import get_logger

logger = get_logger(__name__)

class RedisCache:
    _instance: Optional[Redis] = None
    _lock = asyncio.Lock()

    @classmethod
    async def get_instance(cls) -> Redis:
        if cls._instance is None:
            async with cls._lock:
                if cls._instance is None:
                    try:
                        # Simple connection without complex SSL handling
                        cls._instance = await aioredis.from_url(
                            settings.REDIS_URL,
                            password=settings.REDIS_PASSWORD if settings.REDIS_PASSWORD else None,
                            encoding="utf-8",
                            decode_responses=True,
                            health_check_interval=30,
                            socket_connect_timeout=5,
                            socket_timeout=5,
                            retry_on_timeout=True
                        )
                        logger.info("Redis cache client initialized successfully.")
                    except Exception as e:
                        logger.error(f"Failed to initialize Redis cache client: {e}")
                        # Don't raise the exception, let the fallback cache handle it
                        cls._instance = None
        return cls._instance

    @classmethod
    async def get(cls, key: str) -> Optional[Any]:
        try:
            redis_client = await cls.get_instance()
            if redis_client is None:
                return None
            value = await redis_client.get(key)
            if value:
                return json.loads(value)
        except Exception as e:
            logger.error(f"Error getting key '{key}' from Redis cache: {e}")
        return None

    @classmethod
    async def set(cls, key: str, value: Any, ttl: int = 300):
        try:
            redis_client = await cls.get_instance()
            if redis_client is None:
                return
            await redis_client.setex(key, ttl, json.dumps(value, default=str))
        except Exception as e:
            logger.error(f"Error setting key '{key}' in Redis cache: {e}")

    @classmethod
    async def delete(cls, key: str):
        try:
            redis_client = await cls.get_instance()
            if redis_client is None:
                return
            await redis_client.delete(key)
        except Exception as e:
            logger.error(f"Error deleting key '{key}' from Redis cache: {e}")

    @classmethod
    async def clear_pattern(cls, pattern: str) -> int:
        try:
            redis_client = await cls.get_instance()
            if redis_client is None:
                return 0
            keys = []
            async for key in redis_client.scan_iter(match=pattern):
                keys.append(key)
            if keys:
                await redis_client.delete(*keys)
                logger.info(f"Cleared {len(keys)} keys matching pattern '{pattern}' from Redis cache.")
                return len(keys)
        except Exception as e:
            logger.error(f"Error clearing pattern '{pattern}' from Redis cache: {e}")
        return 0

    @classmethod
    async def acquire_lock(cls, key: str, expire: int = 10) -> bool:
        """SET NX lock for stampede protection. Fail-open (True) when Redis is down."""
        try:
            redis_client = await cls.get_instance()
            if redis_client is None:
                return True
            return bool(await redis_client.set(key, "1", ex=expire, nx=True))
        except Exception as e:
            logger.warning(f"Redis acquire_lock failed for '{key}': {e}")
            return True

    @classmethod
    async def release_lock(cls, key: str):
        try:
            redis_client = await cls.get_instance()
            if redis_client is None:
                return
            await redis_client.delete(key)
        except Exception as e:
            logger.warning(f"Redis release_lock failed for '{key}': {e}")

    @classmethod
    async def incr_stat(cls, key: str) -> None:
        try:
            redis_client = await cls.get_instance()
            if redis_client is None:
                return
            await redis_client.incr(key)
        except Exception:
            pass

    @classmethod
    async def get_stats(cls) -> dict:
        """Hit/miss counters for product cache observability. Fail-open to zeros."""
        try:
            redis_client = await cls.get_instance()
            if redis_client is None:
                return {"hits": 0, "misses": 0, "hit_rate": 0.0, "connected": False}
            hits = await redis_client.get("cache:stats:prod:hits") or 0
            misses = await redis_client.get("cache:stats:prod:misses") or 0
            hits, misses = int(hits), int(misses)
            total = hits + misses
            return {
                "hits": hits,
                "misses": misses,
                "hit_rate": round(hits / total, 3) if total else 0.0,
                "connected": True,
            }
        except Exception as e:
            logger.warning(f"Redis get_stats failed: {e}")
            return {"hits": 0, "misses": 0, "hit_rate": 0.0, "connected": False}

    @classmethod
    async def health_check(cls) -> bool:
        try:
            redis_client = await cls.get_instance()
            if redis_client is None:
                return False
            return await redis_client.ping()
        except Exception as e:
            logger.error(f"Redis health check failed: {e}")
            return False
