"""WhatsApp Cloud API webhook for LEL Store.

GET  /webhooks/whatsapp   Meta's one-time verification handshake
POST /webhooks/whatsapp   inbound messages (signature-checked, handled in background)
"""

import asyncio
import json
import logging

from fastapi import APIRouter, BackgroundTasks, HTTPException, Query, Request, status
from fastapi.responses import PlainTextResponse

from core.whatsapp_agent import handle_payload
from core.whatsapp_models import ensure_whatsapp_tables
from core.whatsapp_service import wa, wa_settings

logger = logging.getLogger("lel_store_backend.whatsapp")

router = APIRouter()

# Creates the whatsapp_links table on first start (safe to run repeatedly).
ensure_whatsapp_tables()

# Cart reminders (one nudge 30 min after the customer stops chatting). Never blocks startup.
try:
    from core.whatsapp_extras import start_reminder_worker

    start_reminder_worker()
except Exception:
    logger.exception("Could not start the WhatsApp reminder worker")


@router.get("")
async def verify_webhook(
    hub_mode: str = Query("", alias="hub.mode"),
    hub_challenge: str = Query("", alias="hub.challenge"),
    hub_verify_token: str = Query("", alias="hub.verify_token"),
):
    """Meta calls this once when you save the webhook URL."""
    expected = wa_settings.WHATSAPP_VERIFY_TOKEN
    if hub_mode == "subscribe" and expected and hub_verify_token == expected:
        return PlainTextResponse(hub_challenge)
    raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Verification failed")


@router.post("")
async def receive_webhook(request: Request, background: BackgroundTasks):
    raw = await request.body()
    if not wa.verify_signature(raw, request.headers.get("x-hub-signature-256")):
        logger.warning("WhatsApp webhook signature check failed")
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Invalid signature")
    try:
        payload = json.loads(raw)
    except ValueError:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid JSON")

    # Answer Meta right away; do the real work in the background.
    background.add_task(handle_payload, payload, asyncio.get_running_loop())
    return {"status": "received"}
