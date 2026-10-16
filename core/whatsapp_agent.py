"""LEL Store WhatsApp shopping assistant.

Flow: onboarding (email + OTP) -> search -> cart -> checkout -> bank-transfer
payment -> receipt. It reuses the store's own services (product search,
order/cart, Flutterwave bank transfer, receipts) so WhatsApp, the website and
the app all share the same cart and orders.

The customer's cart IS their pending Order (same as the website).
"""

from __future__ import annotations

import asyncio
import difflib
import json
import logging
import re
import time
import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from types import SimpleNamespace
from typing import Any, Dict, List, Literal, Optional

import redis
from fastapi import HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import func
from sqlalchemy.orm import Session, joinedload

from core.auth_service import auth_service
from core.config import settings
from core.discounts import effective_price_expr
from core.ml_search_parser import parse_search_query
from core.model import (
    Address,
    Category,
    DeliveryState,
    Order,
    Payment,
    Product,
    Profile,
    User,
)
from core.order import order_service
from core.payment_service import payment_service
from core.products import product_service
from core.system_settings_service import system_settings_service
from core.whatsapp_models import WhatsAppLink
from core.whatsapp_service import clip, wa, wa_settings
from db.session import SessionLocal

logger = logging.getLogger("lel_store_backend.whatsapp")

STATE_TTL = 3600  # seconds a conversation step is remembered
RESULTS_PER_PAGE = 5
OTP_MAX_ATTEMPTS = 5
MSG_RATE_LIMIT = 30  # messages per phone per minute
PAYMENT_WATCH_SECONDS = 3700
EMAIL_RE = re.compile(r"[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}")
WAT = timezone(timedelta(hours=1))  # Nigeria, no daylight saving

STATUS_LABELS = {
    "processing": "Processing",
    "paid": "Paid ✅",
    "shipped": "On its way 🚚",
    "delivered": "Delivered 📦",
    "cancelled": "Cancelled",
    "partially_shipped": "Partly shipped 🚚",
    "partially_delivered": "Partly delivered 📦",
    "partially_cancelled": "Partly cancelled",
}


# ═════════════════════════════════════════════════════════════
# small helpers
# ═════════════════════════════════════════════════════════════
def naira(value: Any) -> str:
    d = Decimal(str(value or 0))
    return f"₦{d:,.0f}" if d == d.to_integral_value() else f"₦{d:,.2f}"


def mask_email(email: str) -> str:
    local, _, domain = email.partition("@")
    return f"{local[:1]}***@{domain}"


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


def get_state(phone: str) -> Dict[str, Any]:
    raw = _r().get(f"wa:state:{phone}")
    return json.loads(raw) if raw else {}


def update_state(phone: str, **fields: Any) -> Dict[str, Any]:
    state = get_state(phone)
    state.update(fields)
    _r().set(f"wa:state:{phone}", json.dumps(state), ex=STATE_TTL)
    return state


def _rate_limited(phone: str) -> bool:
    key = f"wa:rl:{phone}:{int(time.time() // 60)}"
    count = _r().incr(key)
    if count == 1:
        _r().expire(key, 90)
    return count > MSG_RATE_LIMIT


class Ctx:
    """Everything a handler needs for one inbound message."""

    def __init__(self, db: Session, phone: str, loop, wa_name: Optional[str]):
        self.db = db
        self.phone = phone
        self.loop = loop
        self.wa_name = wa_name
        self.user: Optional[User] = None
        self.profile: Optional[Profile] = None

    @property
    def state(self) -> Dict[str, Any]:
        return get_state(self.phone)


# ═════════════════════════════════════════════════════════════
# entry point
# ═════════════════════════════════════════════════════════════
def handle_payload(payload: Dict[str, Any], loop) -> None:
    """Process one Meta webhook payload (runs in a worker thread)."""
    for entry in payload.get("entry", []) or []:
        for change in entry.get("changes", []) or []:
            value = change.get("value", {}) or {}
            names = {
                c.get("wa_id"): (c.get("profile") or {}).get("name")
                for c in value.get("contacts", []) or []
            }
            for msg in value.get("messages", []) or []:
                _process_message(msg, names, loop)


def _process_message(msg: Dict[str, Any], names: Dict[str, Any], loop) -> None:
    phone = msg.get("from")
    msg_id = msg.get("id")
    if not phone or not msg_id:
        return

    # Meta retries webhooks: ignore a message we've already handled.
    if not _r().set(f"wa:seen:{msg_id}", 1, nx=True, ex=86400):
        return

    wa.mark_read(msg_id)

    if _rate_limited(phone):
        wa.send_text(phone, "You're sending messages very quickly. Please wait a moment 🙏")
        return

    mtype = msg.get("type")
    text, reply_id = "", None
    if mtype == "text":
        text = ((msg.get("text") or {}).get("body") or "").strip()
    elif mtype == "interactive":
        inter = msg.get("interactive") or {}
        rep = inter.get("button_reply") or inter.get("list_reply") or {}
        reply_id = rep.get("id")
        text = (rep.get("title") or "").strip()
    elif mtype == "button":
        reply_id = (msg.get("button") or {}).get("payload")
        text = ((msg.get("button") or {}).get("text") or "").strip()
    else:
        wa.send_text(phone, "I can read text messages and buttons for now 🙂 Tell me what you're looking for.")
        return

    db = SessionLocal()
    try:
        ctx = Ctx(db, phone, loop, names.get(phone))
        _route(ctx, text, reply_id)
    except Exception:
        logger.exception("WhatsApp handler failed for %s", phone)
        try:
            db.rollback()
        except Exception:
            pass
        wa.send_text(phone, "Sorry, something went wrong on my side. Please try again in a moment.")
    finally:
        db.close()


def _route(ctx: Ctx, text: str, rid: Optional[str]) -> None:
    db, phone = ctx.db, ctx.phone
    link = db.query(WhatsAppLink).filter(WhatsAppLink.phone == phone).first()
    user = db.query(User).filter(User.id == link.user_id).first() if link else None

    if user is None or user.is_active is False:
        _onboarding(ctx, text, rid)
        return

    profile = db.query(Profile).filter(Profile.id == user.id).first()
    if profile is None:
        wa.send_text(phone, "Your account profile is incomplete. Please contact LEL Store support.")
        return
    ctx.user, ctx.profile = user, profile

    low = text.lower().strip()
    if low in ("cancel", "start over", "reset"):
        update_state(phone, step=None)
        _send_menu(ctx, "No problem, I've cancelled that.")
        return

    if rid:
        _handle_reply(ctx, rid)
        return

    step = ctx.state.get("step")
    if step == "co_state":
        _checkout_state(ctx, text)
        return
    if step == "co_address":
        _checkout_address(ctx, text)
        return

    _handle_text(ctx, text)


# ═════════════════════════════════════════════════════════════
# onboarding (email + OTP)
# ═════════════════════════════════════════════════════════════
def _welcome_buttons(phone: str) -> None:
    wa.send_buttons(
        phone,
        "Hi! 👋 Welcome to *LEL Store*.\n\nI can help you find products, build your cart and pay, "
        "all right here in WhatsApp. First, let's link your account.",
        [("ob:new", "Create account"), ("ob:existing", "I have an account")],
    )


def _onboarding(ctx: Ctx, text: str, rid: Optional[str]) -> None:
    phone, db = ctx.phone, ctx.db
    state = ctx.state
    step = state.get("step")
    low = text.lower().strip()

    if rid == "ob:new":
        update_state(phone, step="ob_name", flow="new")
        wa.send_text(phone, "Great! What's your full name?")
        return
    if rid == "ob:existing":
        update_state(phone, step="ob_email", flow="existing")
        wa.send_text(phone, "What's the email address on your LEL Store account?")
        return
    if low in ("cancel", "restart", "start over"):
        update_state(phone, step=None)
        _welcome_buttons(phone)
        return

    if step == "ob_name":
        name = " ".join(text.split())
        if not (2 <= len(name) <= 80) or "@" in name:
            wa.send_text(phone, "Please send your full name (for example: Ada Obi).")
            return
        update_state(phone, step="ob_email", flow="new", name=name)
        wa.send_text(phone, f"Nice to meet you, {name.split()[0]}! What's your email address?")
        return

    if step == "ob_email":
        m = EMAIL_RE.search(text)
        if not m:
            wa.send_text(phone, "That doesn't look like an email. Please send it like name@example.com")
            return
        email = m.group(0).lower()
        user = db.query(User).filter(func.lower(User.email) == email).first()
        flow = state.get("flow", "new")

        if flow == "existing" and user is None:
            update_state(phone, step=None)
            wa.send_buttons(
                phone,
                f"I couldn't find an account for {email}. Would you like to create one?",
                [("ob:new", "Create account"), ("ob:existing", "Try another email")],
            )
            return

        if user is None:  # brand-new account
            name = state.get("name") or ctx.wa_name or email.split("@")[0]
            user = User(email=email, hashed_password=None, role="customer", email_verified=False)
            db.add(user)
            db.flush()
            db.add(Profile(id=user.id, name=name, phone="+" + phone))
            db.commit()
            db.refresh(user)
            _send_code(ctx, user, "verify")
            return

        if flow == "new":
            wa.send_text(phone, "That email already has a LEL Store account, so I'll link this chat to it.")
        if user.is_active is False:
            wa.send_text(phone, "That account has been deactivated. Please contact LEL Store support.")
            return
        _send_code(ctx, user, "verify" if not user.email_verified else "reset")
        return

    if step == "ob_otp":
        _check_code(ctx, text)
        return

    _welcome_buttons(phone)


def _send_code(ctx: Ctx, user: User, mode: str) -> bool:
    """Email a 6-digit code using the store's existing verification system."""
    phone, db = ctx.phone, ctx.db
    try:
        if mode == "verify":
            auth_service.send_verification_email(db, user.email)
        else:
            auth_service.request_password_reset(db, user.email)
    except HTTPException as exc:
        wa.send_text(phone, str(exc.detail))
        return False
    update_state(phone, step="ob_otp", user_id=str(user.id), email=user.email, mode=mode, attempts=0)
    note = ""
    if mode == "reset":
        note = "\n\n(The email may say \"password reset\". That's just how we send codes. Your password is not changed.)"
    wa.send_text(
        phone,
        f"📧 I've sent a 6-digit code to {mask_email(user.email)}.\n"
        f"Reply here with the code to continue. Send *resend* for a new one.{note}",
    )
    return True


def _check_code(ctx: Ctx, text: str) -> None:
    phone, db = ctx.phone, ctx.db
    state = ctx.state
    email, mode = state.get("email"), state.get("mode")
    user_id = state.get("user_id")
    if not (email and mode and user_id):
        update_state(phone, step=None)
        _welcome_buttons(phone)
        return

    if text.lower().strip() == "resend":
        user = db.query(User).filter(User.id == uuid.UUID(user_id)).first()
        if user:
            _send_code(ctx, user, mode)
        return

    code = re.sub(r"\D", "", text)
    if len(code) != 6:
        wa.send_text(phone, "Please send the 6-digit code from the email (or *resend* for a new one).")
        return

    ok = False
    try:
        if mode == "verify":
            auth_service.verify_email(db, email, code)
            ok = True
        else:
            from core.redis_client import verification_manager

            ok = bool(verification_manager.verify_code(email, code, "password_reset"))
    except HTTPException:
        ok = False

    if not ok:
        attempts = int(state.get("attempts", 0)) + 1
        if attempts >= OTP_MAX_ATTEMPTS:
            update_state(phone, step=None, attempts=0)
            wa.send_text(phone, "Too many wrong codes. Let's start again.")
            _welcome_buttons(phone)
            return
        update_state(phone, attempts=attempts)
        wa.send_text(phone, f"That code isn't right or has expired. {OTP_MAX_ATTEMPTS - attempts} tries left. Send *resend* for a new code.")
        return

    # Verified: now (and only now) link this WhatsApp number to the account.
    uid = uuid.UUID(user_id)
    link = db.query(WhatsAppLink).filter(WhatsAppLink.phone == phone).first()
    if link:
        link.user_id = uid
    else:
        db.add(WhatsAppLink(phone=phone, user_id=uid))
    profile = db.query(Profile).filter(Profile.id == uid).first()
    if profile and not profile.phone:
        profile.phone = "+" + phone
    db.commit()

    update_state(phone, step=None, email=None, mode=None, user_id=None, attempts=0)
    ctx.user = db.query(User).filter(User.id == uid).first()
    ctx.profile = profile
    first = (profile.name.split()[0] if profile and profile.name else "there")
    _send_menu(ctx, f"✅ You're all set, {first}! Your WhatsApp is now linked to your LEL Store account.")


# ═════════════════════════════════════════════════════════════
# menu
# ═════════════════════════════════════════════════════════════
def _send_menu(ctx: Ctx, intro: Optional[str] = None) -> None:
    body = (intro + "\n\n" if intro else "") + "What would you like to do?"
    wa.send_buttons(
        ctx.phone,
        body,
        [("menu:shop", "🛍 Shop"), ("menu:cart", "🛒 My cart"), ("menu:orders", "📦 My orders")],
    )


HELP_TEXT = (
    "Just tell me what you're looking for in your own words, for example:\n"
    "• _a fridge under 250k_\n"
    "• _cheapest sneakers_\n"
    "• _add 2_ (after I show results)\n"
    "• _my cart_ / _checkout_ / _my orders_"
)


# ═════════════════════════════════════════════════════════════
# button / list replies
# ═════════════════════════════════════════════════════════════
def _handle_reply(ctx: Ctx, rid: str) -> None:
    phone = ctx.phone
    if rid == "menu:shop":
        wa.send_text(phone, "🛍 What are you looking for?\n\n" + HELP_TEXT)
    elif rid == "menu:cart":
        _send_cart(ctx)
    elif rid == "menu:orders":
        _show_orders(ctx)
    elif rid == "menu:main":
        _send_menu(ctx)
    elif rid.startswith("add:"):
        _add_to_cart(ctx, rid[4:], 1)
    elif rid == "cart:edit":
        _cart_edit_list(ctx)
    elif rid.startswith("rm:"):
        _remove_item(ctx, rid[3:])
    elif rid == "checkout":
        _start_checkout(ctx)
    elif rid == "dt:pickup":
        _finalize_checkout(ctx, "pickup")
    elif rid == "dt:delivery":
        _choose_delivery(ctx)
    elif rid == "addr:new":
        update_state(phone, step="co_state")
        wa.send_text(phone, "Which *state* should we deliver to? (e.g. Lagos)")
    elif rid.startswith("addr:"):
        _finalize_checkout(ctx, "delivery", address_id=rid[5:])
    elif rid == "pay":
        _pay(ctx)
    elif rid == "more":
        _more_results(ctx)
    elif rid == "cancel":
        update_state(phone, step=None)
        _send_menu(ctx, "Cancelled.")
    else:
        _send_menu(ctx)


# ═════════════════════════════════════════════════════════════
# free text -> intent (Gemini, with rule-based fallback)
# ═════════════════════════════════════════════════════════════
class Intent(BaseModel):
    action: Literal[
        "search", "add_to_cart", "view_cart", "remove_from_cart",
        "checkout", "order_status", "help", "other",
    ]
    query: Optional[str] = Field(None, description="Product words only (no filler), for search")
    quantity: Optional[int] = Field(None, description="Quantity if the customer stated one")
    item_ref: Optional[str] = Field(None, description="Result number like '2', cart line number, or product name")


_intent_llm = None


def _get_intent_llm():
    global _intent_llm
    if _intent_llm is None:
        key = wa_settings.WHATSAPP_GEMINI_API_KEY or settings.GEMINI_API_KEY or settings.GOOGLE_API_KEY
        if not key:
            return None
        from langchain_google_genai import ChatGoogleGenerativeAI

        model = ChatGoogleGenerativeAI(
            model=wa_settings.WHATSAPP_MODEL,
            google_api_key=key,
            temperature=0,
            timeout=20,
            max_retries=1,
        )
        _intent_llm = model.with_structured_output(Intent)
    return _intent_llm


def _llm_intent(text: str, state: Dict[str, Any], cart_names: List[str]) -> Optional[Intent]:
    llm = _get_intent_llm()
    if llm is None:
        return None
    results = [f"{r['n']}. {r['name']}" for r in state.get("last_results", [])]
    system = (
        "You classify messages sent to LEL Store's WhatsApp shopping assistant. Pick one action:\n"
        "- search: wants to find or browse products (query = just the product words)\n"
        "- add_to_cart: wants to add an item (item_ref = result number or product name; quantity if stated)\n"
        "- remove_from_cart: item_ref = cart line number or product name\n"
        "- view_cart, checkout, order_status\n"
        "- help: greetings, thanks, what can you do\n"
        "- other: unrelated to shopping\n"
        f"Results currently shown to the customer: {results or 'none'}\n"
        f"Items in their cart: {cart_names or 'none'}"
    )
    try:
        return llm.invoke([("system", system), ("human", text[:500])])
    except Exception:
        logger.exception("Intent model failed; using rules")
        return None


def _rule_intent(text: str) -> Intent:
    t = text.lower()
    if re.search(r"\b(remove|delete)\b", t):
        return Intent(action="remove_from_cart", item_ref=re.sub(r"\b(remove|delete|from|cart|the)\b", "", t).strip() or None)
    if re.search(r"\badd\b", t):
        qty = re.search(r"\b(\d{1,2})\b", t)
        return Intent(action="add_to_cart", item_ref=qty.group(1) if qty else None, quantity=1)
    if re.search(r"\b(cart|basket)\b", t):
        return Intent(action="view_cart")
    if re.search(r"\b(checkout|pay)\b", t):
        return Intent(action="checkout")
    if re.search(r"\b(orders?|track|status)\b", t):
        return Intent(action="order_status")
    if re.fullmatch(r"(hi|hello|hey|help|menu|start|thanks|thank you)\W*", t):
        return Intent(action="help")
    return Intent(action="search", query=text)


def _handle_text(ctx: Ctx, text: str) -> None:
    low = text.lower().strip()
    if low in ("more", "show more", "next"):
        _more_results(ctx)
        return
    if re.fullmatch(r"(hi|hello|hey|help|menu|start)\W*", low):
        _send_menu(ctx, HELP_TEXT)
        return
    if low in ("cart", "my cart"):
        _send_cart(ctx)
        return
    if low in ("checkout", "pay", "pay now"):
        _start_checkout(ctx)
        return
    if low in ("orders", "my orders"):
        _show_orders(ctx)
        return

    pending = _pending(ctx.db, ctx.profile.id)
    cart_names = [i.product.name for i in (pending.order_items if pending else []) if i.product]
    intent = _llm_intent(text, ctx.state, cart_names) or _rule_intent(text)

    action = intent.action
    if action == "search":
        _do_search(ctx, text, intent.query)
    elif action == "add_to_cart":
        _add_by_ref(ctx, intent.item_ref, intent.quantity or 1)
    elif action == "remove_from_cart":
        _remove_by_ref(ctx, intent.item_ref)
    elif action == "view_cart":
        _send_cart(ctx)
    elif action == "checkout":
        _start_checkout(ctx)
    elif action == "order_status":
        _show_orders(ctx)
    elif action == "help":
        _send_menu(ctx, HELP_TEXT)
    else:
        _send_menu(ctx, "I can help you find products and order from LEL Store 🙂")


# ═════════════════════════════════════════════════════════════
# search
# ═════════════════════════════════════════════════════════════
def _price_of(db: Session, product: Product) -> Decimal:
    """Effective (sale-aware) price, computed by the store's own SQL helper."""
    price = db.query(effective_price_expr(Product)).filter(Product.id == product.id).scalar()
    return Decimal(str(price if price is not None else product.price))


def _find_category(db: Session, hint: str) -> Optional[Category]:
    hint = hint.lower().strip()
    for candidate in {hint, hint + "s", hint.rstrip("s")}:
        cat = db.query(Category).filter(func.lower(Category.name) == candidate).first()
        if cat:
            return cat
    return db.query(Category).filter(func.lower(Category.name).contains(hint)).first()


def _do_search(ctx: Ctx, text: str, intent_query: Optional[str], page: int = 1, saved: Optional[Dict] = None) -> None:
    db, phone = ctx.db, ctx.phone
    if saved:
        params = dict(saved)
    else:
        parsed = parse_search_query(text)
        query = parsed.clean_query if parsed.was_nl else (intent_query or text)
        params = {
            "q": query,
            "category_id": None,
            "min_price": parsed.min_price,
            "max_price": parsed.max_price,
            "sort_by": parsed.sort_by,
            "sort_order": parsed.sort_order,
        }
        if parsed.category_hint:
            cat = _find_category(db, parsed.category_hint)
            if cat:
                params["category_id"] = str(cat.id)
            else:
                params["q"] = f"{query or ''} {parsed.category_hint}".strip()

    products, total = product_service.fetch_products(
        db,
        search_query=params.get("q") or None,
        category_id=params.get("category_id"),
        limit=RESULTS_PER_PAGE,
        page=page,
        min_price=params.get("min_price"),
        max_price=params.get("max_price"),
        sort_by=params.get("sort_by"),
        sort_order=params.get("sort_order"),
    )

    if not products:
        filters = []
        if params.get("max_price"):
            filters.append(f"under {naira(params['max_price'])}")
        if params.get("min_price"):
            filters.append(f"over {naira(params['min_price'])}")
        what = params.get("q") or "that"
        extra = f" ({', '.join(filters)})" if filters else ""
        wa.send_buttons(
            phone,
            f"I couldn't find anything for *{what}*{extra}. Try different words or loosen the price.",
            [("menu:shop", "Search again"), ("menu:cart", "🛒 My cart")],
        )
        return

    params["page"] = page
    first_n = (page - 1) * RESULTS_PER_PAGE
    results = []
    for i, p in enumerate(products, start=1):
        price = _price_of(db, p)
        base = Decimal(str(p.price))
        lines = [f"*{i}. {p.name}*"]
        if price < base:
            pct = int((base - price) / base * 100)
            lines.append(f"~{naira(base)}~ *{naira(price)}*  🔥 {pct}% off")
        else:
            lines.append(f"*{naira(price)}*")
        if p.description:
            lines.append(clip(p.description, 120))
        stock = p.stock_quantity or 0
        if 0 < stock <= 5:
            lines.append(f"Only {stock} left")
        image = next((im.image_url for im in (p.images or []) if im.image_url), None)
        wa.send_buttons(phone, "\n".join(lines), [(f"add:{p.id}", "Add to cart")], header_image=image)
        results.append({"n": i, "id": str(p.id), "name": p.name})

    update_state(phone, last_results=results, search=params)
    shown_to = first_n + len(products)
    footer = f"Showing {first_n + 1}-{shown_to} of {total}. Tap *Add to cart*, or tell me what else you need."
    buttons = [("menu:cart", "🛒 View cart")]
    if shown_to < total:
        buttons.insert(0, ("more", "Show more"))
    wa.send_buttons(phone, footer, buttons)


def _more_results(ctx: Ctx) -> None:
    saved = ctx.state.get("search")
    if not saved:
        wa.send_text(ctx.phone, "Tell me what you're looking for and I'll search 🙂")
        return
    _do_search(ctx, "", None, page=int(saved.get("page", 1)) + 1, saved=saved)


# ═════════════════════════════════════════════════════════════
# cart (the pending Order is the cart)
# ═════════════════════════════════════════════════════════════
def _pending(db: Session, profile_id) -> Optional[Order]:
    return order_service.get_orders_by_status(db, str(profile_id), "pending")


def _add_to_cart(ctx: Ctx, product_id: str, qty: int) -> None:
    db, phone = ctx.db, ctx.phone
    try:
        pid = uuid.UUID(product_id)
    except ValueError:
        wa.send_text(phone, "I couldn't find that item. Try searching again.")
        return
    product = (
        db.query(Product)
        .options(joinedload(Product.images))
        .filter(Product.id == pid, Product.status == "active")
        .first()
    )
    if product is None:
        wa.send_text(phone, "Sorry, that item is no longer available.")
        return

    qty = max(1, min(int(qty), 50))
    price = _price_of(db, product)
    pending = _pending(db, ctx.profile.id)
    try:
        if pending:
            order_service.create_order_item(db, pending.id, product.id, qty, float(price))
        else:
            order_service.create_order(
                db, ctx.profile.id, SimpleNamespace(product_id=product.id, quantity=qty), float(price)
            )
    except HTTPException as exc:
        match = re.search(r"Available:\s*(\d+)", str(exc.detail))
        if match:
            wa.send_text(phone, f"Sorry, only {match.group(1)} of *{product.name}* left in stock.")
        else:
            wa.send_text(phone, str(exc.detail))
        return
    _send_cart(ctx, prefix=f"Added *{product.name}* ✅")


def _add_by_ref(ctx: Ctx, ref: Optional[str], qty: int) -> None:
    results = ctx.state.get("last_results", [])
    chosen = None
    if ref:
        ref = ref.strip()
        if ref.isdigit() and 1 <= int(ref) <= len(results):
            chosen = results[int(ref) - 1]
        else:
            names = {r["name"].lower(): r for r in results}
            close = difflib.get_close_matches(ref.lower(), list(names), n=1, cutoff=0.5)
            if close:
                chosen = names[close[0]]
            else:
                found, _ = product_service.fetch_products(ctx.db, search_query=ref, limit=1, page=1)
                if found:
                    chosen = {"id": str(found[0].id), "name": found[0].name}
    elif len(results) == 1:
        chosen = results[0]
    if not chosen:
        wa.send_text(ctx.phone, "Which item would you like? Tap *Add to cart* on one of the results, or tell me the name.")
        return
    _add_to_cart(ctx, chosen["id"], qty)


def _cart_lines(order: Order) -> List[str]:
    lines = []
    for i, it in enumerate(order.order_items or [], start=1):
        name = it.product.name if it.product else "Item"
        sub = Decimal(str(it.price)) * it.quantity
        lines.append(f"{i}. {name} × {it.quantity}: {naira(sub)}")
    return lines


def _subtotal(order: Order) -> Decimal:
    return sum(
        (Decimal(str(i.price)) * i.quantity for i in (order.order_items or [])), Decimal("0")
    )


def _send_cart(ctx: Ctx, prefix: Optional[str] = None) -> None:
    pending = _pending(ctx.db, ctx.profile.id)
    if not pending or not pending.order_items:
        wa.send_buttons(
            ctx.phone,
            (prefix + "\n\n" if prefix else "") + "Your cart is empty 🛒",
            [("menu:shop", "🛍 Shop")],
        )
        return
    body = (prefix + "\n\n" if prefix else "") + "🛒 *Your cart*\n" + "\n".join(_cart_lines(pending))
    body += f"\n\n*Subtotal:* {naira(_subtotal(pending))}"
    if len(body) > 950:
        wa.send_text(ctx.phone, body)
        body = "What would you like to do next?"
    wa.send_buttons(
        ctx.phone,
        body,
        [("checkout", "Checkout"), ("menu:shop", "Keep shopping"), ("cart:edit", "Edit cart")],
    )


def _cart_edit_list(ctx: Ctx) -> None:
    pending = _pending(ctx.db, ctx.profile.id)
    if not pending or not pending.order_items:
        _send_cart(ctx)
        return
    rows = [
        {
            "id": f"rm:{it.id}",
            "title": (it.product.name if it.product else "Item"),
            "description": f"× {it.quantity} · {naira(Decimal(str(it.price)) * it.quantity)}",
        }
        for it in pending.order_items[:10]
    ]
    wa.send_list(ctx.phone, "Pick an item to remove from your cart:", "Choose item", rows, "Cart items")


def _remove_item(ctx: Ctx, item_id: str) -> None:
    pending = _pending(ctx.db, ctx.profile.id)
    if not pending:
        _send_cart(ctx)
        return
    try:
        result = order_service.delete_order_item(ctx.db, pending.id, uuid.UUID(item_id))
    except ValueError:
        result = None
    if result is None:
        wa.send_text(ctx.phone, "I couldn't find that item in your cart.")
        return
    _send_cart(ctx, prefix="Removed ✅")


def _remove_by_ref(ctx: Ctx, ref: Optional[str]) -> None:
    pending = _pending(ctx.db, ctx.profile.id)
    if not pending or not pending.order_items:
        _send_cart(ctx)
        return
    items = list(pending.order_items)
    target = None
    if ref:
        ref = ref.strip()
        if ref.isdigit() and 1 <= int(ref) <= len(items):
            target = items[int(ref) - 1]
        else:
            names = {(i.product.name if i.product else "").lower(): i for i in items}
            close = difflib.get_close_matches(ref.lower(), list(names), n=1, cutoff=0.4)
            if close:
                target = names[close[0]]
    if target is None:
        _cart_edit_list(ctx)
        return
    _remove_item(ctx, str(target.id))


# ═════════════════════════════════════════════════════════════
# orders
# ═════════════════════════════════════════════════════════════
def _show_orders(ctx: Ctx) -> None:
    orders = (
        ctx.db.query(Order)
        .options(joinedload(Order.order_items))
        .filter(Order.buyer_id == ctx.profile.id, Order.status != "pending")
        .order_by(Order.created_at.desc())
        .limit(3)
        .all()
    )
    if not orders:
        wa.send_buttons(ctx.phone, "You don't have any orders yet.", [("menu:shop", "🛍 Shop")])
        return
    lines = ["📦 *Your recent orders*"]
    for o in orders:
        label = STATUS_LABELS.get(o.status, str(o.status).title())
        if o.status == "shipped" and o.delivery_type == "pickup":
            label = "Ready for pickup 🏬"
        count = len(o.order_items or [])
        lines.append(
            f"\n#{str(o.id)[:8]} · {label}\n{count} item(s) · {naira(o.total_amount)}"
        )
    wa.send_buttons(ctx.phone, "\n".join(lines), [("menu:shop", "🛍 Shop"), ("menu:cart", "🛒 My cart")])


# ═════════════════════════════════════════════════════════════
# checkout
# ═════════════════════════════════════════════════════════════
def _start_checkout(ctx: Ctx) -> None:
    db, phone = ctx.db, ctx.phone
    pending = _pending(db, ctx.profile.id)
    if not pending or not pending.order_items:
        _send_cart(ctx)
        return
    try:
        system_settings_service.require_verified_email_for_user(db, str(ctx.user.id), "check out")
    except HTTPException as exc:
        wa.send_text(phone, str(exc.detail))
        return
    cfg = system_settings_service.get_or_create_settings(db)
    pickup = cfg.store_pickup_location or "our store"
    wa.send_buttons(
        phone,
        f"How would you like to get your order?\n\n🏬 Pickup: {pickup}\n🚚 Delivery to your address",
        [("dt:pickup", "Pick up"), ("dt:delivery", "Delivery"), ("cancel", "Cancel")],
    )


def _choose_delivery(ctx: Ctx) -> None:
    db, phone = ctx.db, ctx.phone
    saved = (
        db.query(Address)
        .filter(Address.user_id == ctx.profile.id)
        .order_by(Address.is_default.desc(), Address.created_at.desc())
        .first()
    )
    if saved:
        wa.send_buttons(
            phone,
            f"Deliver to your saved address?\n\n📍 {saved.street_address}, {saved.city}, {saved.state_province}",
            [(f"addr:{saved.id}", "Use this address"), ("addr:new", "New address"), ("cancel", "Cancel")],
        )
        return
    update_state(phone, step="co_state")
    wa.send_text(phone, "Which *state* should we deliver to? (e.g. Lagos)")


def _checkout_state(ctx: Ctx, text: str) -> None:
    db, phone = ctx.db, ctx.phone
    states = db.query(DeliveryState).filter(DeliveryState.is_active.is_(True)).all()
    by_name = {s.state_name.lower(): s for s in states}
    q = re.sub(r"\bstate\b", "", text.lower()).strip()
    match = by_name.get(q)
    if match is None:
        close = difflib.get_close_matches(q, list(by_name), n=1, cutoff=0.7)
        match = by_name[close[0]] if close else None
    if match is None:
        names = ", ".join(sorted(s.state_name for s in states))[:600]
        wa.send_buttons(
            phone,
            f"Sorry, we don't deliver to *{text}* yet.\nWe deliver to: {names or 'no states yet'}\n\nType another state, or choose pickup.",
            [("dt:pickup", "Pick up instead"), ("cancel", "Cancel")],
        )
        return
    update_state(phone, step="co_address", co_state_id=str(match.id))
    wa.send_text(phone, f"Got it, {match.state_name}. Now send your *delivery address* (street, area, city).")


def _checkout_address(ctx: Ctx, text: str) -> None:
    db, phone = ctx.db, ctx.phone
    street = " ".join(text.split())
    if len(street) < 8:
        wa.send_text(phone, "Please send a fuller address (street, area, city).")
        return
    state_id = ctx.state.get("co_state_id")
    state = db.query(DeliveryState).filter(DeliveryState.id == uuid.UUID(state_id)).first() if state_id else None
    if state is None:
        update_state(phone, step="co_state")
        wa.send_text(phone, "Which *state* should we deliver to?")
        return
    parts = [p.strip() for p in street.split(",") if p.strip()]
    city = parts[-1] if len(parts) > 1 else state.state_name
    address = Address(
        user_id=ctx.profile.id,
        title="WhatsApp",
        street_address=street[:255],
        city=city[:100],
        state_province=state.state_name,
        delivery_state_id=state.id,
        postal_code="000000",
        country="Nigeria",
        is_default=False,
    )
    db.add(address)
    db.commit()
    db.refresh(address)
    update_state(phone, step=None)
    _finalize_checkout(ctx, "delivery", address_id=str(address.id))


def _finalize_checkout(ctx: Ctx, delivery_type: str, address_id: Optional[str] = None) -> None:
    """Mirror of POST /checkout/process: set delivery details and total."""
    db, phone = ctx.db, ctx.phone
    pending = _pending(db, ctx.profile.id)
    if not pending or not pending.order_items:
        _send_cart(ctx)
        return

    subtotal = _subtotal(pending)
    cfg = system_settings_service.get_or_create_settings(db)
    fee = Decimal("0")

    if delivery_type == "delivery":
        try:
            aid = uuid.UUID(address_id or "")
        except ValueError:
            wa.send_text(phone, "I couldn't find that address. Let's try again.")
            _choose_delivery(ctx)
            return
        address = (
            db.query(Address)
            .options(joinedload(Address.delivery_state))
            .filter(Address.id == aid, Address.user_id == ctx.profile.id)
            .first()
        )
        if address is None:
            wa.send_text(phone, "I couldn't find that address. Let's try again.")
            _choose_delivery(ctx)
            return
        state = address.delivery_state
        if state and state.is_active and state.delivery_price is not None:
            fee = Decimal(str(state.delivery_price))
        else:
            fee = Decimal(str(cfg.base_delivery_price or 0))
        pending.delivery_address = address.id
        pending.pickup_location = None
        pending.pickup_address = None
        where = f"🚚 Delivery to: {address.street_address}, {address.city}"
    else:
        pending.pickup_location = cfg.store_pickup_location or "Store Location"
        pending.pickup_address = cfg.store_pickup_address
        pending.delivery_address = None
        where = f"🏬 Pickup: {pending.pickup_location}"
        if pending.pickup_address:
            where += f"\n{pending.pickup_address}"

    pending.delivery_type = delivery_type
    pending.delivery_fee = fee
    pending.total_amount = subtotal + fee
    db.commit()
    db.refresh(pending)
    update_state(phone, co_ready=str(pending.id))

    summary = (
        "🧾 *Order summary*\n"
        + "\n".join(_cart_lines(pending))
        + f"\n\nSubtotal: {naira(subtotal)}"
        + f"\nDelivery: {naira(fee) if fee else 'Free'}"
        + f"\n*Total: {naira(pending.total_amount)}*\n\n{where}"
    )
    wa.send_buttons(phone, summary, [("pay", "Pay now"), ("cancel", "Cancel")])


# ═════════════════════════════════════════════════════════════
# payment (Flutterwave bank transfer)
# ═════════════════════════════════════════════════════════════
def _extract_transfer(data: Any) -> Dict[str, Any]:
    d = data if isinstance(data, dict) else {}
    nested = d.get("bank_transfer") or d.get("transfer") or {}
    if not isinstance(nested, dict):
        nested = {}

    def pick(*keys: str):
        for key in keys:
            for source in (d, nested):
                if source.get(key):
                    return source[key]
        return None

    return {
        "account_number": pick("account_number", "transfer_account"),
        "bank_name": pick("bank_name", "transfer_bank"),
        "account_name": pick("account_name", "transfer_note"),
        "expires_at": pick("expires_at", "account_expiration"),
        "tx_ref": pick("tx_ref", "reference", "transaction_id"),
    }


def _fmt_expiry(value: Any) -> Optional[str]:
    if not value:
        return None
    try:
        dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(WAT).strftime("%I:%M %p").lstrip("0")
    except ValueError:
        return None


def _pay(ctx: Ctx) -> None:
    db, phone = ctx.db, ctx.phone
    pending = _pending(db, ctx.profile.id)
    if not pending or not pending.order_items:
        _send_cart(ctx)
        return
    if ctx.state.get("co_ready") != str(pending.id):
        wa.send_text(phone, "Let's confirm your delivery details first.")
        _start_checkout(ctx)
        return

    # Don't create a second bank account if they tap "Pay now" twice.
    cached = _r().get(f"wa:payinfo:{pending.id}")
    if cached:
        wa.send_text(phone, cached)
        return
    if not _r().set(f"wa:paying:{pending.id}", 1, nx=True, ex=60):
        wa.send_text(phone, "One moment, I'm still generating your payment details…")
        return

    try:
        system_settings_service.require_verified_email_for_user(db, str(ctx.user.id), "initialize a payment")
        data = payment_service.initialize_bank_transfer_payment(
            db=db,
            user_id=str(ctx.user.id),
            email=ctx.user.email,
            amount_naira=Decimal(str(pending.total_amount)),
            category="order",
            order_id=str(pending.id),
            agreement_id=None,
            metadata={"channel": "whatsapp"},
            fullname=ctx.profile.name,
            phone_number=None,
        )
    except HTTPException as exc:
        _r().delete(f"wa:paying:{pending.id}")
        wa.send_text(phone, str(exc.detail))
        return
    except Exception:
        _r().delete(f"wa:paying:{pending.id}")
        logger.exception("Bank transfer init failed")
        wa.send_text(phone, "I couldn't generate your payment details right now. Please try again in a minute.")
        return

    info = _extract_transfer(data)
    if not info["account_number"]:
        logger.error("Could not read bank transfer details. Response keys: %s", list(data.keys()) if isinstance(data, dict) else type(data))
        wa.send_text(phone, "Your order is saved, but I couldn't read the payment details. You can finish payment at lelstore.com.")
        return

    until = _fmt_expiry(info["expires_at"])
    text = (
        f"💳 *Pay {naira(pending.total_amount)} by bank transfer*\n\n"
        f"Bank: *{info['bank_name'] or '-'}*\n"
        f"Account number: *{info['account_number']}*\n"
        f"Account name: {info['account_name'] or 'LEL Store'}\n"
        f"Amount: *{naira(pending.total_amount)}* (send the exact amount)\n"
        + (f"Valid until: {until}\n" if until else "")
        + "\nI'll confirm here as soon as your payment lands ✅"
    )
    _r().set(f"wa:payinfo:{pending.id}", text, ex=3600)
    wa.send_text(phone, text)
    wa.send_text(phone, str(info["account_number"]))  # separate message so it's easy to copy
    update_state(phone, step=None)

    if ctx.loop is not None:
        _spawn(ctx.loop, _watch_payment, str(pending.id), phone, str(ctx.user.id), info.get("tx_ref"))


_TASKS: set = set()


def _spawn(loop, coro_fn, *args) -> None:
    """Start a background coroutine on the server's event loop from a worker thread."""

    def _start():
        task = loop.create_task(coro_fn(*args))
        _TASKS.add(task)
        task.add_done_callback(_TASKS.discard)

    loop.call_soon_threadsafe(_start)


def _payment_state(order_id: str, tx_ref: Optional[str], verify_now: bool) -> Optional[str]:
    """Return 'paid', 'cancelled' or None. Runs in a thread with its own session."""
    db = SessionLocal()
    try:
        oid = uuid.UUID(order_id)

        def completed() -> bool:
            return (
                db.query(Payment.id)
                .filter(Payment.order_id == oid, Payment.status == "completed")
                .first()
                is not None
            )

        if completed():
            return "paid"
        order = db.query(Order).filter(Order.id == oid).first()
        if order is not None and order.status == "cancelled":
            return "cancelled"
        if verify_now:
            pend = (
                db.query(Payment)
                .filter(Payment.order_id == oid, Payment.status == "pending")
                .order_by(Payment.created_at.desc())
                .first()
            )
            ref = (pend.reference or pend.transaction_id) if pend else tx_ref
            if ref:
                try:
                    payment_service.verify_transaction(db, ref)
                except Exception:
                    logger.debug("verify_transaction not complete yet for %s", ref)
                db.expire_all()
                if completed():
                    return "paid"
        return None
    finally:
        db.close()


async def _watch_payment(order_id: str, phone: str, user_id: str, tx_ref: Optional[str]) -> None:
    deadline = time.monotonic() + PAYMENT_WATCH_SECONDS
    tick = 0
    while time.monotonic() < deadline:
        await asyncio.sleep(15)
        tick += 1
        try:
            state = await asyncio.to_thread(_payment_state, order_id, tx_ref, tick % 4 == 0)
        except Exception:
            logger.exception("Payment watch error for order %s", order_id)
            continue
        if state == "paid":
            await asyncio.to_thread(_announce_paid, order_id, phone, user_id)
            return
        if state == "cancelled":
            return
    await asyncio.to_thread(
        wa.send_text,
        phone,
        "⏳ I didn't receive your transfer and the account number has expired. Say *checkout* to get a new one.",
    )


def _announce_paid(order_id: str, phone: str, user_id: str) -> None:
    _r().delete(f"wa:payinfo:{order_id}")
    db = SessionLocal()
    try:
        oid = uuid.UUID(order_id)
        order = db.query(Order).filter(Order.id == oid).first()
        total = naira(order.total_amount) if order else ""
        wa.send_text(
            phone,
            f"✅ *Payment received!*\n\nOrder #{order_id[:8]} · {total}\n"
            "Thank you for shopping with LEL Store. I'll keep you posted here as your order moves.",
        )
        _send_receipt(db, oid, phone, user_id)
        wa.send_buttons(phone, "Anything else?", [("menu:shop", "🛍 Shop"), ("menu:orders", "📦 My orders")])
    except Exception:
        logger.exception("Failed to announce payment for %s", order_id)
    finally:
        db.close()


def _send_receipt(db: Session, order_id, phone: str, user_id: str) -> None:
    """Send the store's own receipt PDF as a WhatsApp document."""
    try:
        from core import receipt_service
        from core.fpdf_receipt_service import render_receipt_pdf

        payment = (
            db.query(Payment)
            .filter(Payment.order_id == order_id, Payment.status == "completed")
            .order_by(Payment.created_at.desc())
            .first()
        )
        if payment is None:
            return
        receipt = receipt_service.get_receipt(db, {"id": user_id, "role": "customer"}, payment.id)
        if not receipt:
            return
        pdf = render_receipt_pdf(receipt)
        number = receipt.get("receipt_number") or str(payment.id)[:8]
        filename = "".join(c if (c.isalnum() or c in "._-") else "_" for c in f"{number}.pdf")
        media_id = wa.upload_media(pdf, "application/pdf", filename)
        if media_id:
            wa.send_document(phone, media_id, filename, "Your LEL Store receipt 🧾")
    except Exception:
        logger.exception("Receipt send failed for order %s", order_id)
