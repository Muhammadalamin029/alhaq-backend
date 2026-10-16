"""WhatsApp Cloud API client for LEL Store.

Sends text / buttons / lists / images / documents and verifies Meta's webhook
signature. Self-contained: reads its own WHATSAPP_* environment variables so
core/config.py does not need to change.

Environment variables (set them in Zeabur > lelstore-backend > Variable):
    WHATSAPP_ACCESS_TOKEN      Meta access token (temporary 24h token for testing)
    WHATSAPP_PHONE_NUMBER_ID   Phone number ID from API Setup
    WHATSAPP_VERIFY_TOKEN      Any string you invent; paste the same one in Meta's webhook form
    WHATSAPP_APP_SECRET        App secret (Meta app > App settings > Basic). Signs webhooks.
    WHATSAPP_GEMINI_API_KEY    Gemini key for the bot (falls back to GEMINI_API_KEY / GOOGLE_API_KEY)
Optional:
    WHATSAPP_GRAPH_VERSION     default v23.0
    WHATSAPP_MODEL             default gemini-3.1-flash-lite
"""

import hashlib
import hmac
import logging
from typing import Any, Dict, List, Optional, Sequence, Tuple

import requests
from pydantic_settings import BaseSettings, SettingsConfigDict

logger = logging.getLogger("lel_store_backend.whatsapp")


class WhatsAppSettings(BaseSettings):
    WHATSAPP_ACCESS_TOKEN: str = ""
    WHATSAPP_PHONE_NUMBER_ID: str = ""
    WHATSAPP_VERIFY_TOKEN: str = ""
    WHATSAPP_APP_SECRET: str = ""
    WHATSAPP_GRAPH_VERSION: str = "v23.0"
    WHATSAPP_GEMINI_API_KEY: str = ""
    WHATSAPP_MODEL: str = "gemini-3.1-flash-lite"
    ENVIRONMENT: str = "development"

    model_config = SettingsConfigDict(env_file=".env", case_sensitive=True, extra="ignore")


wa_settings = WhatsAppSettings()


def clip(text: Optional[str], limit: int) -> str:
    """Trim text to WhatsApp's field limits."""
    text = (text or "").strip()
    return text if len(text) <= limit else text[: limit - 1].rstrip() + "…"


class WhatsAppClient:
    def __init__(self, cfg: WhatsAppSettings = wa_settings):
        self.cfg = cfg

    # ── internals ──────────────────────────────────────────────
    @property
    def _base(self) -> str:
        return (
            f"https://graph.facebook.com/{self.cfg.WHATSAPP_GRAPH_VERSION}"
            f"/{self.cfg.WHATSAPP_PHONE_NUMBER_ID}"
        )

    def _headers(self) -> Dict[str, str]:
        return {"Authorization": f"Bearer {self.cfg.WHATSAPP_ACCESS_TOKEN}"}

    def _configured(self) -> bool:
        if not self.cfg.WHATSAPP_ACCESS_TOKEN or not self.cfg.WHATSAPP_PHONE_NUMBER_ID:
            logger.error("WhatsApp is not configured (missing access token or phone number id)")
            return False
        return True

    def _post_message(self, payload: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """POST to /messages. Never raises: a failed send must not break the flow."""
        if not self._configured():
            return None
        body = {"messaging_product": "whatsapp", "recipient_type": "individual", **payload}
        try:
            resp = requests.post(
                f"{self._base}/messages", json=body, headers=self._headers(), timeout=20
            )
        except requests.RequestException as exc:
            logger.error("WhatsApp send error: %s", exc)
            return None
        if resp.status_code >= 400:
            logger.error("WhatsApp send failed (%s): %s", resp.status_code, resp.text[:600])
            return None
        return resp.json()

    # ── message types ──────────────────────────────────────────
    def send_text(self, to: str, body: str) -> Optional[Dict[str, Any]]:
        return self._post_message(
            {"to": to, "type": "text", "text": {"body": clip(body, 4096), "preview_url": False}}
        )

    def send_buttons(
        self,
        to: str,
        body: str,
        buttons: Sequence[Tuple[str, str]],
        header_image: Optional[str] = None,
        footer: Optional[str] = None,
    ) -> Optional[Dict[str, Any]]:
        """Reply buttons (max 3). buttons = [(id, title), ...]; title max 20 chars."""
        interactive: Dict[str, Any] = {
            "type": "button",
            "body": {"text": clip(body, 1024)},
            "action": {
                "buttons": [
                    {"type": "reply", "reply": {"id": bid[:256], "title": clip(title, 20)}}
                    for bid, title in list(buttons)[:3]
                ]
            },
        }
        if footer:
            interactive["footer"] = {"text": clip(footer, 60)}
        payload: Dict[str, Any] = {"to": to, "type": "interactive", "interactive": interactive}
        if header_image:
            with_image = dict(interactive)
            with_image["header"] = {"type": "image", "image": {"link": header_image}}
            result = self._post_message({**payload, "interactive": with_image})
            if result is not None:
                return result
            # Meta could not fetch the image: retry without it.
        return self._post_message(payload)

    def send_list(
        self,
        to: str,
        body: str,
        button_text: str,
        rows: List[Dict[str, str]],
        section_title: str = "Options",
    ) -> Optional[Dict[str, Any]]:
        """List message (max 10 rows). rows = [{"id","title","description"?}]."""
        clean_rows = []
        for row in rows[:10]:
            item = {"id": row["id"][:200], "title": clip(row["title"], 24)}
            if row.get("description"):
                item["description"] = clip(row["description"], 72)
            clean_rows.append(item)
        return self._post_message(
            {
                "to": to,
                "type": "interactive",
                "interactive": {
                    "type": "list",
                    "body": {"text": clip(body, 1024)},
                    "action": {
                        "button": clip(button_text, 20),
                        "sections": [{"title": clip(section_title, 24), "rows": clean_rows}],
                    },
                },
            }
        )

    def send_document(
        self, to: str, media_id: str, filename: str, caption: Optional[str] = None
    ) -> Optional[Dict[str, Any]]:
        doc: Dict[str, Any] = {"id": media_id, "filename": filename}
        if caption:
            doc["caption"] = clip(caption, 1024)
        return self._post_message({"to": to, "type": "document", "document": doc})

    def upload_media(self, data: bytes, mime_type: str, filename: str) -> Optional[str]:
        """Upload a file to WhatsApp and return its media id."""
        if not self._configured():
            return None
        try:
            resp = requests.post(
                f"{self._base}/media",
                headers=self._headers(),
                data={"messaging_product": "whatsapp", "type": mime_type},
                files={"file": (filename, data, mime_type)},
                timeout=60,
            )
        except requests.RequestException as exc:
            logger.error("WhatsApp media upload error: %s", exc)
            return None
        if resp.status_code >= 400:
            logger.error("WhatsApp media upload failed (%s): %s", resp.status_code, resp.text[:600])
            return None
        return resp.json().get("id")

    def mark_read(self, message_id: str) -> None:
        """Mark inbound message read and show the typing indicator. Best effort."""
        if not self._configured():
            return
        try:
            requests.post(
                f"{self._base}/messages",
                json={
                    "messaging_product": "whatsapp",
                    "status": "read",
                    "message_id": message_id,
                    "typing_indicator": {"type": "text"},
                },
                headers=self._headers(),
                timeout=10,
            )
        except requests.RequestException:
            pass

    # ── webhook signature ──────────────────────────────────────
    def verify_signature(self, raw_body: bytes, header: Optional[str]) -> bool:
        """Check Meta's X-Hub-Signature-256 header against WHATSAPP_APP_SECRET."""
        secret = self.cfg.WHATSAPP_APP_SECRET
        is_production = self.cfg.ENVIRONMENT.lower() == "production"
        if not secret:
            if is_production:
                logger.error("WHATSAPP_APP_SECRET not set in production. Rejecting webhook.")
                return False
            logger.warning("WHATSAPP_APP_SECRET not set. Skipping signature check (non-production).")
            return True
        if not header or not header.startswith("sha256="):
            return False
        expected = hmac.new(secret.encode("utf-8"), raw_body, hashlib.sha256).hexdigest()
        return hmac.compare_digest(expected, header.split("=", 1)[1])


wa = WhatsAppClient()
