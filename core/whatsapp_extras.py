"""Extras for the LEL Store WhatsApp assistant.

1. Languages  : English, Yoruba, Igbo, Hausa and Nigerian Pidgin. Every message
                the bot sends (text, buttons, lists) is translated into the
                customer's saved language automatically, so the whole experience
                (cards, cart, checkout) speaks their language, not just the chat.
2. Voice notes: download the WhatsApp audio, transcribe it with Gemini, and
                treat it like a typed message (also detects the language).
3. Reminders  : one friendly cart reminder, 30 minutes after the customer stops
                chatting (only if the cart still has items).

Everything here is best-effort: if translation, transcription or a reminder
fails, the bot carries on in English / asks the customer to type.
"""

from __future__ import annotations

import base64
import hashlib
import json
import logging
import re
import threading
import time
from typing import Any, Dict, List, Optional, Sequence, Tuple

import redis

from core.config import settings
from core.whatsapp_service import clip, wa, wa_settings

logger = logging.getLogger("lel_store_backend.whatsapp")

LANGS: Dict[str, str] = {
    "en": "English",
    "yo": "Yoruba",
    "ig": "Igbo",
    "ha": "Hausa",
    "pcm": "Nigerian Pidgin",
}
TRANSLATION_TTL = 7 * 24 * 3600
MAX_AUDIO_BYTES = 10 * 1024 * 1024

# ═════════════════════════════════════════════════════════════
# shared plumbing
# ═════════════════════════════════════════════════════════════
_redis_client: Optional[redis.Redis] = None


def _r() -> redis.Redis:
    global _redis_client
    if _redis_client is None:
        _redis_client = redis.Redis.from_url(
            settings.REDIS_URL,
            password=settings.REDIS_PASSWORD or None,
            decode_responses=True,
        )
    return _redis_client


_llm = None


def _get_llm():
    global _llm
    if _llm is None:
        key = wa_settings.WHATSAPP_GEMINI_API_KEY or settings.GEMINI_API_KEY or settings.GOOGLE_API_KEY
        if not key:
            return None
        from langchain_google_genai import ChatGoogleGenerativeAI

        _llm = ChatGoogleGenerativeAI(
            model=wa_settings.WHATSAPP_MODEL,
            google_api_key=key,
            temperature=0.2,
            timeout=40,
            max_retries=1,
        )
    return _llm


def _llm_text(msg) -> str:
    c = getattr(msg, "content", "")
    if isinstance(c, str):
        return c.strip()
    out = []
    for block in c or []:
        if isinstance(block, str):
            out.append(block)
        elif isinstance(block, dict) and block.get("type") == "text":
            out.append(block.get("text", ""))
    return "".join(out).strip()


def _json_from(text: str) -> Any:
    """Pull the first JSON object/array out of a model reply."""
    text = re.sub(r"^```(?:json)?|```$", "", text.strip(), flags=re.M).strip()
    starts = [(text.find(o), o, c) for o, c in (("{", "}"), ("[", "]")) if text.find(o) != -1]
    for start, _, closer in sorted(starts):  # whichever opens first is the outer value
        end = text.rfind(closer)
        if end > start:
            try:
                return json.loads(text[start : end + 1])
            except ValueError:
                continue
    return None


# ═════════════════════════════════════════════════════════════
# 1. languages
# ═════════════════════════════════════════════════════════════
def get_lang(phone: str) -> str:
    try:
        code = _r().get(f"wa:lang:{phone}")
    except Exception:
        return "en"
    return code if code in LANGS else "en"


def set_lang(phone: str, code: str) -> str:
    code = (code or "").strip().lower()
    if code not in LANGS:
        return get_lang(phone)
    try:
        _r().set(f"wa:lang:{phone}", code)  # no expiry: it's a preference
    except Exception:
        logger.exception("Could not save language")
    return code


_NUM_RE = re.compile(r"\d[\d,\.]*\d|\d")


def _numbers_preserved(original: str, translated: str) -> bool:
    """Amounts, account numbers, codes and order refs must survive translation untouched."""
    needed = {n for n in _NUM_RE.findall(original)}
    return all(n in translated for n in needed)


def _translate_batch(lang: str, items: List[Tuple[str, Optional[int]]]) -> Optional[List[str]]:
    llm = _get_llm()
    if llm is None:
        return None
    payload = [
        {"i": i, "text": text, **({"max_chars": limit} if limit else {})}
        for i, (text, limit) in enumerate(items)
    ]
    prompt = (
        f"Translate these WhatsApp messages from LEL Store (a shop in Nigeria) from English into "
        f"{LANGS[lang]}. Write natural, friendly, everyday {LANGS[lang]} the way a young Nigerian "
        f"would text it (use correct tone marks/diacritics where they normally apply).\n"
        "STRICT RULES:\n"
        "- Keep unchanged: product names and brand names, ₦ amounts and every number, order "
        "references, account/bank details, codes, emails, URLs, emojis, and the WhatsApp "
        "formatting marks (*bold*, _italic_, ~strike~, line breaks, bullets).\n"
        "- Do not add, remove or reorder information. Do not explain anything.\n"
        "- If an item has max_chars, the translation MUST be at most that many characters "
        "(these are button labels: keep them short).\n"
        'Reply with ONLY a JSON array of objects like [{"i":0,"text":"..."}], one per input, '
        "same order.\n\nINPUT:\n" + json.dumps(payload, ensure_ascii=False)
    )
    try:
        data = _json_from(_llm_text(llm.invoke([("human", prompt)])))
    except Exception:
        logger.exception("Translation call failed")
        return None
    if not isinstance(data, list):
        return None
    by_i = {d.get("i"): d.get("text") for d in data if isinstance(d, dict)}
    out = []
    for i, (original, limit) in enumerate(items):
        t = by_i.get(i)
        if not isinstance(t, str) or not t.strip() or not _numbers_preserved(original, t):
            out.append(original)  # anything doubtful stays in English
        else:
            out.append(clip(t, limit) if limit else t)
    return out


def localize(phone: str, items: Sequence[Tuple[str, Optional[int]]]) -> List[str]:
    """Translate [(text, max_chars)] into the customer's language. Never raises."""
    texts = [t for t, _ in items]
    try:
        lang = get_lang(phone)
        if lang == "en":
            return texts
        result: List[Optional[str]] = [None] * len(items)
        missing: List[int] = []
        keys = []
        for i, (text, limit) in enumerate(items):
            if not text or not text.strip() or not re.search(r"[A-Za-z]", text):
                result[i] = text
                keys.append(None)
                continue
            key = f"wa:tr:{lang}:{hashlib.sha1(f'{limit}|{text}'.encode()).hexdigest()}"
            keys.append(key)
            cached = _r().get(key)
            if cached:
                result[i] = cached
            else:
                missing.append(i)
        if missing:
            translated = _translate_batch(lang, [items[i] for i in missing])
            for pos, i in enumerate(missing):
                value = translated[pos] if translated else items[i][0]
                result[i] = value
                if translated and value != items[i][0]:
                    _r().set(keys[i], value, ex=TRANSLATION_TTL)
        return [r if r is not None else texts[i] for i, r in enumerate(result)]
    except Exception:
        logger.exception("Localize failed; sending English")
        return texts


# every message the bot sends now goes through this hook
wa.localizer = localize


# ═════════════════════════════════════════════════════════════
# 2. voice notes
# ═════════════════════════════════════════════════════════════
def transcribe_voice(media_id: str) -> Tuple[str, Optional[str]]:
    """WhatsApp voice note -> (text, language code or None). ('' if it failed)."""
    llm = _get_llm()
    if llm is None:
        return "", None
    media = wa.download_media(media_id)
    if not media:
        return "", None
    data, mime = media
    if not data or len(data) > MAX_AUDIO_BYTES:
        return "", None
    mime = (mime or "audio/ogg").split(";")[0].strip() or "audio/ogg"
    prompt = (
        "This is a WhatsApp voice note sent to a shop's assistant in Nigeria. The speaker may use "
        "English, Nigerian Pidgin, Yoruba, Igbo or Hausa (or a mix). Transcribe exactly what they "
        "said, in the language they spoke (do not translate). "
        'Reply with ONLY JSON: {"language": "en|yo|ig|ha|pcm", "text": "<transcript>"}. '
        'If nothing intelligible was said, use an empty text.'
    )
    try:
        from langchain_core.messages import HumanMessage

        msg = HumanMessage(
            content=[
                {"type": "text", "text": prompt},
                {"type": "media", "mime_type": mime, "data": base64.b64encode(data).decode()},
            ]
        )
        parsed = _json_from(_llm_text(llm.invoke([msg])))
    except Exception:
        logger.exception("Voice transcription failed")
        return "", None
    if not isinstance(parsed, dict):
        return "", None
    text = str(parsed.get("text") or "").strip()
    lang = str(parsed.get("language") or "").strip().lower()
    return text[:800], (lang if lang in LANGS else None)


# ═════════════════════════════════════════════════════════════
# 3. cart reminders
# ═════════════════════════════════════════════════════════════
REMINDER_QUEUE = "wa:remind:q"
REMINDER_COOLDOWN = 12 * 3600       # never remind the same person more than this often
WINDOW_SECONDS = 23 * 3600          # WhatsApp only allows free-form messages within 24h of their last message
_worker_started = False
_worker_lock = threading.Lock()


def touch(phone: str) -> None:
    """Customer just chatted: (re)start their 30-minute countdown."""
    if not wa_settings.WHATSAPP_REMINDERS:
        return
    try:
        due = time.time() + max(1, wa_settings.WHATSAPP_REMINDER_MINUTES) * 60
        _r().zadd(REMINDER_QUEUE, {phone: due})
    except Exception:
        logger.exception("Could not schedule cart reminder")


def _send_reminder(phone: str) -> None:
    from core import whatsapp_agent as agent
    from core.model import Profile, User
    from core.whatsapp_models import WhatsAppLink
    from db.session import SessionLocal

    db = SessionLocal()
    try:
        link = db.query(WhatsAppLink).filter(WhatsAppLink.phone == phone).first()
        user = db.query(User).filter(User.id == link.user_id).first() if link else None
        if user is None or user.is_active is False:
            return
        profile = db.query(Profile).filter(Profile.id == user.id).first()
        if profile is None:
            return
        pending = agent._pending(db, profile.id)
        if not pending or not pending.order_items:
            return
        # payment already started for this cart: don't nag
        if _r().get(f"wa:payinfo:{pending.id}"):
            return
        if not _r().set(f"wa:remind:sent:{phone}", 1, nx=True, ex=REMINDER_COOLDOWN):
            return

        first = ""
        full = getattr(profile, "full_name", None) or getattr(profile, "name", None) or ""
        if full:
            first = full.split()[0]
        lines = agent._cart_lines(pending)
        subtotal = agent._subtotal(pending)
        body = (
            f"👋 Hi{(' ' + first) if first else ''}, you left something in your cart:\n\n"
            + "\n".join(lines)
            + f"\n\n*Subtotal: {agent.naira(subtotal)}*\n\nReady to complete your order? 🛍"
        )
        wa.send_buttons(
            phone,
            body,
            [("checkout", "Checkout"), ("menu:cart", "View cart"), ("menu:shop", "Keep shopping")],
        )
        logger.info("Cart reminder sent to %s", phone)
    except Exception:
        logger.exception("Cart reminder failed for %s", phone)
        try:
            db.rollback()
        except Exception:
            pass
    finally:
        db.close()


def _worker_loop() -> None:
    while True:
        try:
            now = time.time()
            due = _r().zrangebyscore(REMINDER_QUEUE, 0, now, start=0, num=25, withscores=True)
            for phone, score in due:
                # zrem is atomic: if several server workers race, only one gets 1
                if _r().zrem(REMINDER_QUEUE, phone) != 1:
                    continue
                if now - score > WINDOW_SECONDS - 30 * 60:
                    continue  # too old (server was down); WhatsApp wouldn't deliver it
                _send_reminder(phone)
        except Exception:
            logger.exception("Reminder worker error")
        time.sleep(30)


def start_reminder_worker() -> None:
    """Start the background poller once per server process."""
    global _worker_started
    if not wa_settings.WHATSAPP_REMINDERS:
        return
    with _worker_lock:
        if _worker_started:
            return
        _worker_started = True
    threading.Thread(target=_worker_loop, name="wa-cart-reminders", daemon=True).start()
    logger.info("WhatsApp cart reminder worker started (%s min)", wa_settings.WHATSAPP_REMINDER_MINUTES)
