"""Expo Push API delivery for customer devices.

Sends via https://exp.host/--/api/v2/push/send (no FCM server key needed).
Invalid/expired tokens reported by Expo are deactivated locally.
"""
from typing import Dict, List, Optional

import requests

from core.logging_config import get_logger

logger = get_logger("core.push_service")

EXPO_PUSH_URL = "https://exp.host/--/api/v2/push/send"
REQUEST_TIMEOUT = 10


def chunk(tokens: List[str], size: int = 100) -> List[List[str]]:
    return [tokens[i:i + size] for i in range(0, len(tokens), size)]


def send_expo_push(
    tokens: List[str],
    title: str,
    body: str,
    data: Optional[Dict] = None,
) -> Dict[str, int]:
    """Send a push to Expo push tokens. Returns {sent, failed}."""
    tokens = [t for t in tokens if t and t.startswith("ExponentPushToken[")]
    if not tokens:
        return {"sent": 0, "failed": 0}

    sent, failed = 0, 0
    bad_tokens: List[str] = []
    for batch in chunk(tokens):
        messages = [
            {"to": t, "sound": "default", "title": title, "body": body, "data": data or {}}
            for t in batch
        ]
        try:
            resp = requests.post(EXPO_PUSH_URL, json=messages, timeout=REQUEST_TIMEOUT)
            resp.raise_for_status()
            ticket = resp.json()
        except Exception as e:
            logger.error(f"Expo push request failed: {e}")
            failed += len(batch)
            continue

        receipts = ticket.get("data", []) if isinstance(ticket, dict) else []
        for token, receipt in zip(batch, receipts):
            if not isinstance(receipt, dict):
                continue
            if receipt.get("status") == "ok":
                sent += 1
            else:
                failed += 1
                details = receipt.get("details", {}) or {}
                if details.get("error") in ("DeviceNotRegistered", "InvalidCredentials"):
                    bad_tokens.append(token)
                else:
                    logger.error(f"Expo push ticket error for {token}: {receipt}")

    if bad_tokens:
        try:
            from db.session import SessionLocal
            from core.model import PushDeviceToken

            db = SessionLocal()
            try:
                db.query(PushDeviceToken).filter(
                    PushDeviceToken.expo_push_token.in_(bad_tokens)
                ).update({"is_active": False}, synchronize_session=False)
                db.commit()
            finally:
                db.close()
        except Exception as e:
            logger.error(f"Failed to deactivate bad push tokens: {e}")

    return {"sent": sent, "failed": failed}
