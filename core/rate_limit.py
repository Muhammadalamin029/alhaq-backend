"""Brute-force protection for sensitive endpoints.

Redis-backed fixed-window counters (shared across workers) with an
in-memory fallback so auth never breaks when Redis is down. Exceeding a
rule returns 429 + Retry-After instead of touching the handler.
"""
import time
from typing import Dict, List, Tuple

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse

from core.logging_config import get_logger

logger = get_logger("core.rate_limit")

# (method, path prefix, max requests, window seconds)
RULES: List[Tuple[str, str, int, int]] = [
    ("POST", "/auth/login", 10, 60),
    ("POST", "/auth/register", 5, 60),
    ("POST", "/auth/google", 10, 60),
    ("POST", "/auth/request-password-reset", 5, 60),
    ("POST", "/auth/reset-password", 5, 60),
    ("POST", "/auth/verify-email", 10, 60),
    ("POST", "/auth/send-verification", 10, 60),
    ("POST", "/auth/resend-verification", 10, 60),
    ("POST", "/auth/refresh", 30, 60),
]

# process-local fallback: key -> (count, window_start)
_fallback: Dict[str, Tuple[int, float]] = {}


def _client_ip(request: Request) -> str:
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


def _match_rule(method: str, path: str):
    for rule_method, prefix, limit, window in RULES:
        if method == rule_method and path.startswith(prefix):
            return limit, window
    return None


async def _redis_allowed(key: str, limit: int, window: int):
    """Returns (allowed, retry_after_seconds) using Redis, or None if Redis is down."""
    try:
        from core.redis_cache import RedisCache

        client = await RedisCache.get_instance()
        if client is None:
            return None
        count = await client.incr(key)
        if count == 1:
            await client.expire(key, window)
        ttl = await client.ttl(key)
        return count <= limit, max(0, ttl if ttl and ttl > 0 else window)
    except Exception as e:
        logger.warning(f"Rate-limit Redis unavailable, using memory fallback: {e}")
        return None


def _memory_allowed(key: str, limit: int, window: int):
    now = time.time()
    count, start = _fallback.get(key, (0, now))
    if now - start >= window:
        count, start = 0, now
    count += 1
    _fallback[key] = (count, start)
    # opportunistic prune
    if len(_fallback) > 10000:
        cutoff = now - window
        for k in [k for k, (_, s) in _fallback.items() if s < cutoff]:
            _fallback.pop(k, None)
    return count <= limit, max(0, int(window - (now - start)))


class RateLimitMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        rule = _match_rule(request.method, request.url.path)
        if rule is None:
            return await call_next(request)

        limit, window = rule
        key = f"rl:{request.url.path}:{_client_ip(request)}"

        decided = await _redis_allowed(key, limit, window)
        if decided is None:
            decided = _memory_allowed(key, limit, window)
        allowed, retry_after = decided

        if not allowed:
            logger.warning(f"Rate limit exceeded: {key} ({limit}/{window}s)")
            return JSONResponse(
                status_code=429,
                content={"detail": "Too many requests. Please try again shortly."},
                headers={"Retry-After": str(retry_after)},
            )
        return await call_next(request)
