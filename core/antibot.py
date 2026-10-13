"""Anti-bot helpers for public registration.

- Honeypot: frontend sends a hidden `website` field that humans leave empty.
- Disposable email domain blocklist: rejects throwaway domains used by bot waves.
- Turnstile verification: optional. When TURNSTILE_SECRET_KEY is configured,
  the frontend must send a token; verification failure rejects signup.
  When unconfigured (local dev), verification is skipped so signup keeps working.
"""
from __future__ import annotations

import logging
from typing import Optional

logger = logging.getLogger(__name__)

# Curated set of throwaway domains seen in bot waves. Kept small and
# maintainable; extend as new waves appear.
DISPOSABLE_DOMAINS = frozenset(
    {
        "mailinator.com",
        "guerrillamail.com",
        "guerrillamail.net",
        "sharklasers.com",
        "grr.la",
        "10minutemail.com",
        "10minutemail.net",
        "tempmail.com",
        "temp-mail.org",
        "throwawaymail.com",
        "yopmail.com",
        "yopmail.net",
        "fakemail.net",
        "maildrop.cc",
        "getnada.com",
        "mohmal.com",
        "dispostable.com",
        "trashmail.com",
        "trashmail.net",
        "mintemail.com",
        "mytemp.email",
        "tempail.com",
        "emailondeck.com",
        "mailnesia.com",
        "spamgourmet.com",
        "0-mail.com",
        "0815.ru",
    }
)


def is_disposable_email(email: str) -> bool:
    try:
        domain = email.strip().split("@", 1)[1].lower()
    except (IndexError, AttributeError):
        return False
    # Subdomains of a disposable root (e.g. x.yopmail.com) also count.
    return any(domain == d or domain.endswith("." + d) for d in DISPOSABLE_DOMAINS)


def verify_turnstile_token(token: Optional[str], remote_ip: Optional[str] = None) -> bool:
    """Verify a Cloudflare Turnstile token. Returns True when skipped (no key)."""
    from core.config import settings

    secret = (getattr(settings, "TURNSTILE_SECRET_KEY", "") or "").strip()
    if not secret:
        return True  # not configured -> do not block legitimate signups
    if not token:
        return False
    try:
        import requests

        resp = requests.post(
            "https://challenges.cloudflare.com/turnstile/v0/siteverify",
            data={"secret": secret, "response": token, **({"remoteip": remote_ip} if remote_ip else {})},
            timeout=10,
        )
        data = resp.json()
        ok = bool(data.get("success"))
        if not ok:
            logger.warning(f"Turnstile verification failed: {data.get('error-codes')}")
        return ok
    except Exception as e:
        logger.warning(f"Turnstile verification error (fail-open): {e}")
        return True  # fail-open so auth never breaks on provider outage
