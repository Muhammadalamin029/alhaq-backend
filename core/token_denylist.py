"""Server-side revocation for stateless JWT refresh tokens.

Logout and single-use refresh rotation add token hashes here; the
/refresh endpoint rejects anything listed. Backed by Redis with
fail-open semantics (a Redis outage never locks every user out).
"""

import hashlib

from core.config import settings
from core.logging_config import get_logger

logger = get_logger(__name__)

PREFIX = "token_denylist:"

_client = None


def _client_or_none():
    global _client
    if _client is not None:
        return _client
    try:
        import redis

        kwargs: dict = {
            "socket_connect_timeout": 3,
            "socket_timeout": 3,
        }
        # Only pass an explicit password when configured; otherwise a
        # password embedded in REDIS_URL is used as-is.
        if settings.REDIS_PASSWORD:
            kwargs["password"] = settings.REDIS_PASSWORD
        _client = redis.Redis.from_url(settings.REDIS_URL, **kwargs)
        return _client
    except Exception as e:
        logger.error(f"Token denylist Redis unavailable: {e}")
        return None


def _key(token: str) -> str:
    digest = hashlib.sha256(token.encode("utf-8")).hexdigest()
    return f"{PREFIX}{digest}"


def denylist_token(token: str, ttl_seconds: int) -> None:
    """Revoke a refresh token. Fail-open: logs and continues on Redis errors."""
    client = _client_or_none()
    if client is None:
        return
    try:
        client.setex(_key(token), ttl_seconds, "1")
    except Exception as e:
        logger.error(f"Failed to denylist token: {e}")


def is_denylisted(token: str) -> bool:
    """True when the token was revoked. Fail-open (False) on Redis errors."""
    client = _client_or_none()
    if client is None:
        return False
    try:
        return bool(client.exists(_key(token)))
    except Exception as e:
        logger.error(f"Failed to check token denylist: {e}")
        return False
