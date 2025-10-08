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
    async def clear_pattern(cls, pattern: str):
        try:
            redis_client = await cls.get_instance()
            if redis_client is None:
                return
            keys = []
            async for key in redis_client.scan_iter(match=pattern):
                keys.append(key)
            if keys:
                await redis_client.delete(*keys)
                logger.info(f"Cleared {len(keys)} keys matching pattern '{pattern}' from Redis cache.")
        except Exception as e:
            logger.error(f"Error clearing pattern '{pattern}' from Redis cache: {e}")

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
