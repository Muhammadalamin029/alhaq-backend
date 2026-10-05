"""Short-TTL Redis cache-aside for product storefront reads.

List TTL 90s, detail TTL 300s. Search queries bypass cache (low hit rate).
Fail-open: any Redis error returns None so requests fall through to Postgres.
"""
import hashlib
import json
from typing import Any, Optional

from core.redis_cache import RedisCache
from core.logging_config import get_logger

logger = get_logger(__name__)

LIST_TTL = 90
DETAIL_TTL = 300
VERSION = "v1"
LIST_PREFIX = f"prod:{VERSION}:list"
DETAIL_PREFIX = f"prod:{VERSION}:detail"


def build_list_key(
    page: int,
    limit: int,
    category_id: Optional[str] = None,
    min_price: Optional[float] = None,
    max_price: Optional[float] = None,
    status: Optional[str] = None,
    sort_by: Optional[str] = None,
    sort_order: Optional[str] = None,
) -> str:
    raw = "|".join(
        [
            f"page={page}",
            f"limit={limit}",
            f"cat={category_id or ''}",
            f"min={min_price if min_price is not None else ''}",
            f"max={max_price if max_price is not None else ''}",
            f"status={status or 'active'}",
            f"sort={sort_by or 'created_at'}",
            f"order={sort_order or 'desc'}",
        ]
    )
    return f"{LIST_PREFIX}:{hashlib.md5(raw.encode()).hexdigest()}"


def build_detail_key(product_id: str) -> str:
    return f"{DETAIL_PREFIX}:{product_id}"


async def get_list(key: str) -> Optional[dict]:
    try:
        data = await RedisCache.get(key)
        if data is not None:
            await RedisCache.incr_stat("cache:stats:prod:hits")
            return data
        await RedisCache.incr_stat("cache:stats:prod:misses")
        return None
    except Exception as e:
        logger.warning(f"product list cache get failed: {e}")
        return None


async def set_list(key: str, payload: dict) -> None:
    try:
        # json.dumps with default=str handles UUID/datetime from model_dump(mode="json") anyway
        await RedisCache.set(key, json.loads(json.dumps(payload, default=str)), ttl=LIST_TTL)
    except Exception as e:
        logger.warning(f"product list cache set failed: {e}")


async def get_detail(product_id: str) -> Optional[dict]:
    return await get_list(build_detail_key(str(product_id)))


async def set_detail(product_id: str, payload: dict) -> None:
    try:
        await RedisCache.set(
            build_detail_key(str(product_id)),
            json.loads(json.dumps(payload, default=str)),
            ttl=DETAIL_TTL,
        )
    except Exception as e:
        logger.warning(f"product detail cache set failed: {e}")


async def invalidate_list() -> int:
    return await RedisCache.clear_pattern(f"{LIST_PREFIX}:*")


async def invalidate_detail(product_id: str) -> None:
    await RedisCache.delete(build_detail_key(str(product_id)))


async def invalidate_product(product_id: Optional[str] = None) -> None:
    """Call after any product write. Always clears list; clears detail when id known."""
    try:
        await invalidate_list()
        if product_id:
            await invalidate_detail(product_id)
    except Exception as e:
        logger.warning(f"product cache invalidate failed: {e}")


async def cache_stats() -> dict:
    stats = await RedisCache.get_stats()
    stats.update(
        {
            "list_ttl": LIST_TTL,
            "detail_ttl": DETAIL_TTL,
            "version": VERSION,
        }
    )
    return stats
