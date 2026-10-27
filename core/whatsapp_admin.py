"""LEL Store WhatsApp ADMIN mode.

The store owner says "switch to admin". The first time, the bot asks for the admin
email and emails a 6-digit code (same system the customer login uses). The code is
only accepted when that email belongs to an active user with role = "admin".
After that this phone is remembered as an admin phone.

In admin mode the owner can:
  * add a product (name, price, category, stock, description, discount, photos)
  * see recent orders and pending deliveries, open an order, move it along
    (shipped / delivered / cancelled), the customer is told on WhatsApp
  * see sales today / this month, top seller, low stock
  * change a product's price, stock, or hide/show it
  * get a WhatsApp alert whenever an order is paid (website, app or WhatsApp)

Security rules:
  * admin rights come ONLY from the verified link (phone -> admin user) and are
    re-checked on every message (role still admin, account still active)
  * the store/seller is never taken from chat; it is the store's single profile
  * OTP attempts are rate limited per phone and per email
"""

from __future__ import annotations

import logging
import os
import re
import threading
import time
import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
from typing import Any, Dict, List, Optional

from fastapi import HTTPException
from sqlalchemy import TIMESTAMP, Boolean, Column, ForeignKey, String, UUID as SA_UUID, func
from sqlalchemy import String as SAString
from sqlalchemy import cast
from sqlalchemy.orm import joinedload

from core.model import (
    AssetImage,
    AuditLog,
    Category,
    ExternalPayment,
    Order,
    OrderItem,
    Payment,
    Product,
    Profile,
    StoreProfile,
    User,
)
from core.whatsapp_service import clip, wa
from db.session import Base, SessionLocal

logger = logging.getLogger("lel_store_backend.whatsapp")

WAT = timezone(timedelta(hours=1))
STATE_TTL = 3600
MAX_PHOTOS = 5
EMAIL_RE = re.compile(r"[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}")
SWITCH_ADMIN_RE = re.compile(
    r"^\W*(?:please\s+)?(?:switch(?:\s+me)?\s+to\s+admin(?:\s+mode)?|admin(?:\s+mode)?|go\s+to\s+admin|"
    r"enter\s+admin(?:\s+mode)?|i\s*(?:am|'m)\s+(?:the\s+)?admin|log\s*in\s+as\s+admin)\W*$",
    re.I,
)
SWITCH_CUSTOMER_RE = re.compile(
    r"^\W*(?:switch(?:\s+me)?\s+(?:back\s+)?to\s+(?:customer|shop|shopping|user)(?:\s+mode)?|"
    r"customer\s+mode|shop\s+mode|exit\s+admin(?:\s+mode)?|leave\s+admin(?:\s+mode)?)\W*$",
    re.I,
)
OTP_MAX_ATTEMPTS = 5
OTP_SENDS_PER_HOUR = 5

PENDING_DELIVERY_STATUSES = ["paid", "shipped", "partially_shipped"]
REVENUE_STATUSES = ["paid", "shipped", "delivered", "partially_shipped", "partially_delivered"]

STATUS_TEXT = {
    "pending": "Not paid yet",
    "processing": "Awaiting payment",
    "paid": "Paid ✅, ready to ship",
    "shipped": "Shipped 🚚",
    "delivered": "Delivered 📦",
    "cancelled": "Cancelled ❌",
    "partially_shipped": "Partly shipped 🚚",
    "partially_delivered": "Partly delivered 📦",
    "partially_cancelled": "Partly cancelled",
}


# ═════════════════════════════════════════════════════════════
# admin link table (phone -> verified admin user)
# ═════════════════════════════════════════════════════════════
class WhatsAppAdminLink(Base):
    __tablename__ = "whatsapp_admin_links"

    phone = Column(String(32), primary_key=True)
    user_id = Column(SA_UUID, ForeignKey("users.id"), nullable=False, index=True)
    mode_admin = Column(Boolean, nullable=False, default=True)  # currently in admin mode
    alerts = Column(Boolean, nullable=False, default=True)  # new-order alerts
    created_at = Column(TIMESTAMP, server_default=func.current_timestamp())


def ensure_admin_tables() -> None:
    """Create whatsapp_admin_links if missing (safe to run on every start)."""
    db = SessionLocal()
    try:
        WhatsAppAdminLink.__table__.create(bind=db.get_bind(), checkfirst=True)
    except Exception:
        logger.exception("Could not create whatsapp_admin_links")
    finally:
        db.close()


# ═════════════════════════════════════════════════════════════
# small helpers
# ═════════════════════════════════════════════════════════════
def _agent():
    from core import whatsapp_agent  # lazy: avoids a circular import

    return whatsapp_agent


def naira(v: Any) -> str:
    return _agent().naira(v)


def _say(phone: str, text: str) -> None:
    wa.send_text(phone, text, raw=True)


def _buttons(phone: str, body: str, buttons: List[tuple]) -> None:
    wa.send_buttons(phone, body, buttons[:3], raw=True)


def _list(phone: str, body: str, button: str, rows: List[Dict[str, str]], title: str = "Options") -> None:
    wa.send_list(phone, body, button, rows[:10], title, raw=True)


def _r():
    return _agent()._r()


def _st(phone: str) -> Dict[str, Any]:
    import json

    raw = _r().get(f"wa:adm:st:{phone}")
    return json.loads(raw) if raw else {}


def _set(phone: str, **fields: Any) -> Dict[str, Any]:
    import json

    st = _st(phone)
    st.update(fields)
    _r().set(f"wa:adm:st:{phone}", json.dumps(st), ex=STATE_TTL)
    return st


def _reset(phone: str, **fields: Any) -> None:
    import json

    _r().set(f"wa:adm:st:{phone}", json.dumps(fields), ex=STATE_TTL)


def _clear(phone: str) -> None:
    _r().delete(f"wa:adm:st:{phone}")


def _get_link(db, phone: str) -> Optional[WhatsAppAdminLink]:
    """Never raises: if the table is missing, customers must keep working."""
    try:
        return db.query(WhatsAppAdminLink).filter(WhatsAppAdminLink.phone == phone).first()
    except Exception:
        logger.exception("whatsapp_admin_links lookup failed")
        try:
            db.rollback()
        except Exception:
            pass
        return None


def _parse_amount(text: str) -> Optional[Decimal]:
    t = (text or "").lower().replace("₦", "").replace("ngn", "").replace(",", "").replace(" ", "")
    t = t.lstrip("n")
    m = re.fullmatch(r"(\d+(?:\.\d+)?)(k|m)?", t)
    if not m:
        return None
    try:
        val = Decimal(m.group(1))
    except InvalidOperation:
        return None
    if m.group(2) == "k":
        val *= 1000
    elif m.group(2) == "m":
        val *= 1_000_000
    return val


def _wat_str(dt: Optional[datetime]) -> str:
    if not dt:
        return "-"
    return (dt + timedelta(hours=1)).strftime("%d %b, %I:%M %p").lstrip("0")  # DB stores UTC


# ═════════════════════════════════════════════════════════════
# entry point (called first by the WhatsApp router)
# ═════════════════════════════════════════════════════════════
def intercept(ctx, text: str, rid: Optional[str]) -> bool:
    """True = this message was handled by admin mode and must not reach the customer flow."""
    db, phone = ctx.db, ctx.phone
    low = (text or "").strip().lower()
    image_id = getattr(ctx, "image_id", None)

    link = _get_link(db, phone)
    st = _st(phone)
    step = st.get("step") or ""

    # verification conversation in progress
    if step in ("adm_email", "adm_otp"):
        if low in ("cancel", "stop") or SWITCH_CUSTOMER_RE.match(low):
            _clear(phone)
            _say(phone, "Okay, admin sign-in cancelled.")
            return False  # continue as a normal customer message
        _verify_step(ctx, text, step)
        return True

    if rid is None and SWITCH_ADMIN_RE.match(low):
        _enter_admin(ctx, link)
        return True

    if link is not None and link.mode_admin:
        user = db.query(User).filter(User.id == link.user_id).first()
        if user is None or user.role != "admin" or user.is_active is False:
            # rights were removed on the website: drop this phone out of admin mode for good
            db.delete(link)
            db.commit()
            _clear(phone)
            _say(phone, "Your admin access is no longer active, so I've switched you back to shopping mode.")
            return False
        ctx.admin_mode = True
        _admin(ctx, link, user, text, rid, image_id)
        return True

    return False


# ═════════════════════════════════════════════════════════════
# entering admin mode + email/OTP verification
# ═════════════════════════════════════════════════════════════
def _enter_admin(ctx, link: Optional[WhatsAppAdminLink]) -> None:
    db, phone = ctx.db, ctx.phone
    if link is not None:
        user = db.query(User).filter(User.id == link.user_id).first()
        if user is not None and user.role == "admin" and user.is_active is not False:
            link.mode_admin = True
            db.commit()
            ctx.admin_mode = True
            _reset(phone)
            _admin_menu(ctx, user, "✅ You're in *admin mode*.")
            return
        db.delete(link)
        db.commit()
    _reset(phone, step="adm_email")
    _say(
        phone,
        "🔐 *Admin sign-in*\n\nSend the *email address of your admin account* and I'll email you a 6-digit code.\n"
        "(Send *cancel* to stop.)",
    )


def _rate_ok(phone: str, email: Optional[str] = None) -> bool:
    r = _r()
    k = f"wa:adm:rl:{phone}"
    n = r.incr(k)
    if n == 1:
        r.expire(k, 3600)
    if n > OTP_SENDS_PER_HOUR:
        return False
    if email:
        k2 = f"wa:adm:rle:{email}"
        n2 = r.incr(k2)
        if n2 == 1:
            r.expire(k2, 3600)
        if n2 > OTP_SENDS_PER_HOUR:
            return False
    return True


def _verify_step(ctx, text: str, step: str) -> None:
    db, phone = ctx.db, ctx.phone
    if step == "adm_email":
        m = EMAIL_RE.search(text or "")
        if not m:
            _say(phone, "Please send the admin email like name@example.com (or *cancel*).")
            return
        email = m.group(0).lower()
        if not _rate_ok(phone, email):
            _clear(phone)
            _say(phone, "Too many attempts. Please try again in an hour.")
            return
        user = db.query(User).filter(func.lower(User.email) == email).first()
        if user is None or user.role != "admin" or user.is_active is False:
            _clear(phone)
            _say(phone, "I couldn't verify that email as a store admin account. If you think this is a mistake, "
                        "check the email and say *switch to admin* again.")
            return
        _send_code(ctx, user)
        return

    # adm_otp
    st = _st(phone)
    email, uid, mode = st.get("email"), st.get("user_id"), st.get("mode")
    if not (email and uid and mode):
        _reset(phone, step="adm_email")
        _say(phone, "Let's start again. What's your admin email?")
        return
    low = (text or "").strip().lower()
    if low == "resend":
        user = db.query(User).filter(User.id == uuid.UUID(uid)).first()
        if user is None or user.role != "admin":
            _clear(phone)
            return
        if not _rate_ok(phone, email):
            _clear(phone)
            _say(phone, "Too many attempts. Please try again in an hour.")
            return
        _send_code(ctx, user)
        return
    code = re.sub(r"\D", "", text or "")
    if len(code) != 6:
        _say(phone, "Please send the 6-digit code from the email (or *resend* for a new one).")
        return

    ok = False
    try:
        from core.auth_service import auth_service

        if mode == "verify":
            auth_service.verify_email(db, email, code)
            ok = True
        else:
            from core.redis_client import verification_manager

            ok = bool(verification_manager.verify_code(email, code, "password_reset"))
    except HTTPException:
        ok = False
    except Exception:
        logger.exception("Admin OTP check failed")
        ok = False

    if not ok:
        attempts = int(st.get("attempts", 0)) + 1
        if attempts >= OTP_MAX_ATTEMPTS:
            _clear(phone)
            _say(phone, "Too many wrong codes. Say *switch to admin* to start again.")
            return
        _set(phone, attempts=attempts)
        _say(phone, f"That code isn't right or has expired. {OTP_MAX_ATTEMPTS - attempts} tries left. "
                    "Send *resend* for a new code.")
        return

    # Verified. Re-check the role at the moment of linking, then remember this phone.
    user = db.query(User).filter(User.id == uuid.UUID(uid)).first()
    if user is None or user.role != "admin" or user.is_active is False:
        _clear(phone)
        _say(phone, "I couldn't verify that account as an admin.")
        return
    link = _get_link(db, phone)
    if link:
        link.user_id = user.id
        link.mode_admin = True
    else:
        db.add(WhatsAppAdminLink(phone=phone, user_id=user.id, mode_admin=True, alerts=True))
    db.commit()
    _reset(phone)
    ctx.admin_mode = True
    _admin_menu(ctx, user, "✅ Verified! You're now in *admin mode*. I'll remember this phone.")


def _send_code(ctx, user: User) -> None:
    phone, db = ctx.phone, ctx.db
    mode = "verify" if not user.email_verified else "reset"
    try:
        from core.auth_service import auth_service

        if mode == "verify":
            auth_service.send_verification_email(db, user.email)
        else:
            auth_service.request_password_reset(db, user.email)
    except HTTPException as exc:
        _say(phone, str(exc.detail))
        return
    except Exception:
        logger.exception("Could not send the admin code")
        _say(phone, "I couldn't send the code right now. Please try again in a minute.")
        return
    _reset(phone, step="adm_otp", email=user.email, user_id=str(user.id), mode=mode, attempts=0)
    note = ""
    if mode == "reset":
        note = "\n\n(The email may say \"password reset\". That's just how codes are sent. Your password is not changed.)"
    _say(
        phone,
        f"📧 I've sent a 6-digit code to {_agent().mask_email(user.email)}.\n"
        f"Reply here with the code. Send *resend* for a new one.{note}",
    )


# ═════════════════════════════════════════════════════════════
# admin menu + router
# ═════════════════════════════════════════════════════════════
def _admin_menu(ctx, user: User, intro: Optional[str] = None) -> None:
    link = _get_link(ctx.db, ctx.phone)
    alerts_on = bool(link.alerts) if link else True
    name = (user.name or "").split(" ")[0] if getattr(user, "name", None) else "Admin"
    body = (intro + "\n\n" if intro else "") + f"What would you like to do, {name}?"
    rows = [
        {"id": "adm:new", "title": "➕ Add product", "description": "Upload a new product with photos"},
        {"id": "adm:pending", "title": "🚚 Pending deliveries", "description": "Paid orders waiting to ship or deliver"},
        {"id": "adm:orders", "title": "📦 Recent orders", "description": "Latest orders and their status"},
        {"id": "adm:sales_day", "title": "📊 Sales today", "description": "Today's money and orders"},
        {"id": "adm:sales_month", "title": "📈 Sales this month", "description": "This month's money and top seller"},
        {"id": "adm:products", "title": "🗂 Products & stock", "description": "Low stock first, edit price/stock"},
        {"id": "adm:alerts", "title": "🔔 Order alerts: " + ("ON" if alerts_on else "OFF"),
         "description": "Tap to turn new-order alerts " + ("off" if alerts_on else "on")},
        {"id": "adm:customer", "title": "🛍 Switch to customer", "description": "Shop like a normal customer"},
    ]
    _list(ctx.phone, body, "Admin menu", rows, "Admin")


_WIZARD_RIDS = ("adm:cat:", "adm:skip", "adm:done", "adm:save")


def _admin(ctx, link: WhatsAppAdminLink, user: User, text: str, rid: Optional[str], image_id: Optional[str]) -> None:
    phone, db = ctx.phone, ctx.db
    low = (text or "").strip().lower()
    st = _st(phone)
    step = st.get("step") or ""

    if rid == "adm:customer" or (rid is None and SWITCH_CUSTOMER_RE.match(low)):
        link.mode_admin = False
        db.commit()
        _clear(phone)
        ctx.admin_mode = False
        _say(phone, "🛍 Switched to *customer mode*. Say *switch to admin* any time to come back.")
        _agent()._route(ctx, "hi", None)
        return

    if rid is None and low in ("cancel", "stop", "back"):
        _clear(phone)
        _admin_menu(ctx, user, "Okay, cancelled.")
        return

    if rid:
        if rid.startswith("adm:"):
            if not rid.startswith(_WIZARD_RIDS):  # tapping anything else abandons a half-filled form
                _clear(phone)
            _rid(ctx, link, user, rid, st)
        else:
            # an old customer button tapped while in admin mode
            _admin_menu(ctx, user, "You're in admin mode. Pick an action, or say *switch to customer* to shop.")
        return

    if image_id:
        if step == "ap_photo":
            _wizard_photo(ctx, user, image_id)
        else:
            _say(phone, "To add a product, say *add product* first, then send its photos when I ask.")
        return

    if step:
        _wizard(ctx, user, step, st, text)
        return

    if re.fullmatch(r"(hi|hello|hey|menu|start|help|admin)\W*", low):
        _admin_menu(ctx, user)
    elif re.search(r"\b(add|new|upload|create)\b.*\bproduct\b|\bproduct\b.*\b(add|new|upload)\b", low):
        _start_wizard(ctx)
    elif re.search(r"\bsales?\b.*\b(month|monthly)\b|\b(month|monthly)\b.*\b(sales?|revenue)\b|this month", low):
        _sales(ctx, "month")
    elif re.search(r"\b(sales?|revenue|earned|income)\b|\btoday\b", low):
        _sales(ctx, "day")
    elif re.search(r"pending|deliver|to ship|unshipped", low):
        _order_list(ctx, "pending")
    elif re.search(r"\borders?\b", low):
        _order_list(ctx, "recent")
    elif re.search(r"stock|inventory|products?|low stock", low):
        _product_list(ctx)
    elif re.fullmatch(r"#?[0-9a-f]{6,8}", low):
        _order_by_prefix(ctx, low.lstrip("#"))
    else:
        _admin_menu(ctx, user, "I didn't quite get that. Pick an action below, or say things like "
                               "*sales today*, *pending deliveries*, *add product*.")


def _rid(ctx, link, user, rid: str, st: Dict[str, Any]) -> None:
    phone, db = ctx.phone, ctx.db
    if rid == "adm:menu":
        _admin_menu(ctx, user)
    elif rid == "adm:new":
        _start_wizard(ctx)
    elif rid == "adm:pending":
        _order_list(ctx, "pending")
    elif rid == "adm:orders":
        _order_list(ctx, "recent")
    elif rid == "adm:sales_day":
        _sales(ctx, "day")
    elif rid == "adm:sales_month":
        _sales(ctx, "month")
    elif rid == "adm:products":
        _product_list(ctx)
    elif rid == "adm:alerts":
        link.alerts = not bool(link.alerts)
        db.commit()
        _admin_menu(ctx, user, "🔔 Order alerts are now *" + ("ON" if link.alerts else "OFF") + "*.")
    elif rid.startswith("adm:o:"):
        _order_detail(ctx, rid[6:])
    elif rid.startswith("adm:ship:"):
        _change_status(ctx, user, rid[9:], "shipped")
    elif rid.startswith("adm:deliv:"):
        _change_status(ctx, user, rid[10:], "delivered")
    elif rid.startswith("adm:cx:"):
        oid = rid[7:]
        _buttons(phone, f"Cancel order #{oid[:8]}? Stock goes back on the shelf. "
                        "⚠️ Cancelling does NOT refund money automatically.",
                 [(f"adm:cxy:{oid}", "Yes, cancel it"), (f"adm:o:{oid}", "No, go back")])
    elif rid.startswith("adm:cxy:"):
        _change_status(ctx, user, rid[8:], "cancelled")
    elif rid.startswith("adm:p:"):
        _product_detail(ctx, rid[6:])
    elif rid.startswith("adm:pp:"):
        _reset(phone, step="edit_price", pid=rid[7:])
        _say(phone, "💰 Send the new price in naira (e.g. *250000* or *250k*). Send *cancel* to stop.")
    elif rid.startswith("adm:ps:"):
        _reset(phone, step="edit_stock", pid=rid[7:])
        _say(phone, "📦 Send the new stock quantity (a number). Send *cancel* to stop.")
    elif rid.startswith("adm:pv:"):
        _toggle_product(ctx, rid[7:])
    elif rid.startswith("adm:cat:"):
        _wizard_category(ctx, rid[8:], None)
    elif rid == "adm:skip":
        _wizard(ctx, user, st.get("step", ""), st, "", skipped=True)
    elif rid == "adm:done":
        _wizard_photos_done(ctx)
    elif rid == "adm:save":
        _wizard_save(ctx, user)
    elif rid == "adm:cancel":
        _clear(phone)
        _admin_menu(ctx, user, "Cancelled.")
    else:
        _admin_menu(ctx, user)


# ═════════════════════════════════════════════════════════════
# orders
# ═════════════════════════════════════════════════════════════
def _order_list(ctx, kind: str) -> None:
    db, phone = ctx.db, ctx.phone
    q = db.query(Order).options(joinedload(Order.buyer))
    if kind == "pending":
        q = q.filter(Order.status.in_(PENDING_DELIVERY_STATUSES))
        total = q.count()
        orders = q.order_by(Order.created_at.asc()).limit(10).all()
        title, empty = "🚚 *Pending deliveries*", "🎉 Nothing waiting. Every paid order has been delivered."
    else:
        q = q.filter(Order.status != "pending")
        total = q.count()
        orders = q.order_by(Order.created_at.desc()).limit(10).all()
        title, empty = "📦 *Recent orders*", "No orders yet."
    if not orders:
        _buttons(phone, empty, [("adm:menu", "Admin menu")])
        return
    rows = []
    for o in orders:
        buyer = o.buyer.name if o.buyer and o.buyer.name else "Customer"
        mode = "Pickup" if o.delivery_type == "pickup" else "Delivery"
        rows.append({
            "id": f"adm:o:{o.id}",
            "title": clip(f"#{str(o.id)[:8]} · {naira(o.total_amount)}", 24),
            "description": clip(f"{STATUS_TEXT.get(o.status, o.status)} · {buyer} · {mode}", 72),
        })
    extra = f"\nShowing {len(orders)} of {total}." if total > len(orders) else ""
    _list(phone, f"{title}\n{total} order(s).{extra}\nTap one to open it.", "Open order", rows, "Orders")


def _order_by_prefix(ctx, prefix: str) -> None:
    o = (
        ctx.db.query(Order)
        .filter(cast(Order.id, SAString).like(prefix + "%"), Order.status != "pending")
        .order_by(Order.created_at.desc())
        .first()
    )
    if o is None:
        _say(ctx.phone, f"I couldn't find an order starting with #{prefix}.")
        return
    _order_detail(ctx, str(o.id))


def _load_order(db, oid: str) -> Optional[Order]:
    try:
        u = uuid.UUID(oid)
    except ValueError:
        return None
    return (
        db.query(Order)
        .options(
            joinedload(Order.buyer),
            joinedload(Order.order_items).joinedload(OrderItem.product),
            joinedload(Order.delivery_addr),
        )
        .filter(Order.id == u)
        .first()
    )


def _order_detail(ctx, oid: str) -> None:
    phone, db = ctx.phone, ctx.db
    o = _load_order(db, oid)
    if o is None:
        _say(phone, "I couldn't find that order.")
        return
    buyer = o.buyer
    lines = [f"🧾 *Order #{str(o.id)[:8]}*", f"Status: {STATUS_TEXT.get(o.status, o.status)}"]
    who = (buyer.name if buyer and buyer.name else "Customer")
    if buyer and buyer.phone:
        who += f" · {buyer.phone}"
    lines.append(f"Customer: {who}")
    lines.append("")
    for it in o.order_items or []:
        nm = it.product.name if it.product else "Item"
        lines.append(f"• {it.quantity} × {nm}: {naira(Decimal(str(it.price)) * it.quantity)}")
    fee = Decimal(str(o.delivery_fee or 0))
    lines.append("")
    lines.append(f"Delivery fee: {naira(fee) if fee else 'Free'}")
    lines.append(f"*Total: {naira(o.total_amount)}*")
    if o.delivery_type == "pickup":
        lines.append(f"\n🏬 Pickup: {o.pickup_location or 'Store'}")
    else:
        a = o.delivery_addr
        if a:
            lines.append(f"\n🚚 Deliver to: {a.street_address}, {a.city}, {a.state_province}")
        else:
            lines.append("\n🚚 Delivery (no address saved)")
    lines.append(f"Placed: {_wat_str(o.created_at)}")
    body = "\n".join(lines)

    pick = o.delivery_type == "pickup"
    if o.status == "paid":
        btns = [(f"adm:ship:{o.id}", "Ready for pickup" if pick else "Mark shipped"),
                (f"adm:cx:{o.id}", "Cancel order"), ("adm:menu", "Admin menu")]
    elif o.status in ("shipped", "partially_shipped"):
        btns = [(f"adm:deliv:{o.id}", "Mark collected" if pick else "Mark delivered"),
                ("adm:pending", "Pending list"), ("adm:menu", "Admin menu")]
    elif o.status == "processing":
        btns = [(f"adm:cx:{o.id}", "Cancel order"), ("adm:orders", "Orders"), ("adm:menu", "Admin menu")]
    else:
        btns = [("adm:orders", "Orders"), ("adm:menu", "Admin menu")]
    _buttons(phone, body, btns)


def _change_status(ctx, user: User, oid: str, new_status: str) -> None:
    phone, db = ctx.phone, ctx.db
    o = _load_order(db, oid)
    if o is None:
        _say(phone, "I couldn't find that order.")
        return
    from core.order import order_service

    try:
        order_service.update_order_status(
            db, o.id, new_status, user_id=str(user.id), user_role="admin",
            notes="Updated from WhatsApp admin",
        )
    except HTTPException as exc:
        try:
            db.rollback()
        except Exception:
            pass
        _say(phone, f"⚠️ I couldn't do that: {exc.detail}")
        return
    except Exception:
        logger.exception("Admin status change failed")
        try:
            db.rollback()
        except Exception:
            pass
        _say(phone, "Something went wrong while updating the order. Please try again.")
        return

    label = {"shipped": "Ready for pickup 🏬" if o.delivery_type == "pickup" else "Shipped 🚚",
             "delivered": "Delivered 📦", "cancelled": "Cancelled ❌"}[new_status]
    _buttons(phone, f"✅ Order #{str(o.id)[:8]} is now *{label}*.\nThe customer was notified.",
             [("adm:pending", "Pending list"), ("adm:menu", "Admin menu")])
    _notify_buyer(db, o, new_status)


def _notify_buyer(db, order: Order, new_status: str) -> None:
    """Tell the customer on WhatsApp too (email/push already go out from the order service)."""
    try:
        from core.whatsapp_models import WhatsAppLink

        link = db.query(WhatsAppLink).filter(WhatsAppLink.user_id == order.buyer_id).first()
        if not link:
            return
        ref = str(order.id)[:8]
        pick = order.delivery_type == "pickup"
        msgs = {
            "shipped": (f"🏬 Your order #{ref} is ready for pickup at {order.pickup_location or 'our store'}."
                        if pick else f"🚚 Good news! Your order #{ref} is on its way."),
            "delivered": (f"📦 Your order #{ref} has been collected. Thank you for shopping with LEL Store!"
                          if pick else f"📦 Your order #{ref} has been delivered. Thank you for shopping with LEL Store!"),
            "cancelled": f"Your order #{ref} has been cancelled. Please contact LEL Store if you have questions.",
        }
        wa.send_text(link.phone, msgs[new_status])
    except Exception:
        logger.exception("Could not WhatsApp the customer about order %s", order.id)


# ═════════════════════════════════════════════════════════════
# sales
# ═════════════════════════════════════════════════════════════
def _range_start(kind: str):
    """Start of today / this month in Nigeria time, as a SQL expression.

    Works whatever timezone the database session uses: the naive timestamp columns
    are compared to an absolute moment (midnight in Africa/Lagos).
    """
    unit = "day" if kind == "day" else "month"
    return func.timezone("Africa/Lagos", func.date_trunc(unit, func.timezone("Africa/Lagos", func.now())))


def _sales(ctx, kind: str) -> None:
    db, phone = ctx.db, ctx.phone
    start = _range_start(kind)
    online_amt, online_orders = db.query(
        func.coalesce(func.sum(Payment.amount), 0), func.count(func.distinct(Payment.order_id))
    ).filter(
        Payment.status == "completed", Payment.order_id.isnot(None), Payment.created_at >= start
    ).one()
    off_amt, off_n = db.query(
        func.coalesce(func.sum(ExternalPayment.amount), 0), func.count(ExternalPayment.id)
    ).filter(ExternalPayment.status == "completed", ExternalPayment.paid_at >= start).one()
    to_ship = db.query(Order).filter(Order.status == "paid").count()
    on_way = db.query(Order).filter(Order.status.in_(["shipped", "partially_shipped"])).count()
    top = (
        db.query(Product.name, func.sum(OrderItem.quantity).label("q"))
        .join(OrderItem, OrderItem.product_id == Product.id)
        .join(Order, Order.id == OrderItem.order_id)
        .filter(Order.status.in_(REVENUE_STATUSES), Order.created_at >= start)
        .group_by(Product.name)
        .order_by(func.sum(OrderItem.quantity).desc())
        .first()
    )
    now = datetime.now(WAT)
    label = now.strftime("%a %d %b") if kind == "day" else now.strftime("%B %Y")
    total = Decimal(str(online_amt or 0)) + Decimal(str(off_amt or 0))
    lines = [
        f"📊 *Sales {'today' if kind == 'day' else 'this month'}* ({label})",
        "",
        f"💳 Online: *{naira(online_amt)}* from {int(online_orders or 0)} order(s)",
        f"💵 Recorded offline: {naira(off_amt)} ({int(off_n or 0)} sale(s))",
        f"*Total: {naira(total)}*",
        "",
        f"📦 To ship now: {to_ship}",
        f"🚚 On the way / waiting pickup: {on_way}",
    ]
    if top:
        lines.append(f"🏆 Top seller: {top[0]} ({int(top[1] or 0)} sold)")
    _buttons(phone, "\n".join(lines),
             [("adm:pending", "Pending deliveries"), ("adm:products", "Low stock"), ("adm:menu", "Admin menu")])


# ═════════════════════════════════════════════════════════════
# products: list, edit price / stock / visibility
# ═════════════════════════════════════════════════════════════
def _product_list(ctx) -> None:
    db, phone = ctx.db, ctx.phone
    prods = (
        db.query(Product).filter(Product.status != "inactive")
        .order_by(func.coalesce(Product.stock_quantity, 0).asc(), Product.name.asc()).limit(10).all()
    )
    hidden = db.query(Product).filter(Product.status == "inactive").count()
    if not prods:
        _buttons(phone, "You have no products yet.", [("adm:new", "➕ Add product"), ("adm:menu", "Admin menu")])
        return
    rows = []
    for p in prods:
        stock = p.stock_quantity or 0
        flag = "⚠️ " if stock <= 5 else ""
        rows.append({
            "id": f"adm:p:{p.id}",
            "title": clip(p.name, 24),
            "description": clip(f"{flag}{stock} in stock · {naira(p.price)} · {p.status}", 72),
        })
    note = f"\n({hidden} hidden product(s) not shown)" if hidden else ""
    _list(phone, f"🗂 *Products* (lowest stock first){note}\nTap one to change its price, stock or visibility.",
          "Choose product", rows, "Products")


def _product_detail(ctx, pid: str) -> None:
    db, phone = ctx.db, ctx.phone
    p = _find_product(db, pid)
    if p is None:
        _say(phone, "I couldn't find that product.")
        return
    cat = p.category.name if p.category else "-"
    lines = [f"🛍 *{p.name}*", f"Price: {naira(p.price)}"]
    if p.discount_percent:
        lines.append(f"Discount: {p.discount_percent}%")
    lines += [f"Stock: {p.stock_quantity or 0}", f"Category: {cat}", f"Status: {p.status}"]
    hide = p.status != "inactive"
    _buttons(phone, "\n".join(lines),
             [(f"adm:pp:{p.id}", "Edit price"), (f"adm:ps:{p.id}", "Edit stock"),
              (f"adm:pv:{p.id}", "Hide product" if hide else "Show product")])


def _find_product(db, pid: str) -> Optional[Product]:
    try:
        u = uuid.UUID(pid)
    except ValueError:
        return None
    return db.query(Product).options(joinedload(Product.category)).filter(Product.id == u).first()


def _toggle_product(ctx, pid: str) -> None:
    db, phone = ctx.db, ctx.phone
    p = _find_product(db, pid)
    if p is None:
        _say(phone, "I couldn't find that product.")
        return
    p.status = "active" if p.status == "inactive" else "inactive"
    db.commit()
    _buttons(phone, f"✅ *{p.name}* is now {'visible on the website' if p.status == 'active' else 'hidden'}.",
             [(f"adm:p:{p.id}", "Back to product"), ("adm:products", "Products"), ("adm:menu", "Admin menu")])


def _edit_value(ctx, user: User, step: str, st: Dict[str, Any], text: str) -> None:
    db, phone = ctx.db, ctx.phone
    p = _find_product(db, st.get("pid", ""))
    if p is None:
        _clear(phone)
        _say(phone, "I couldn't find that product.")
        return
    if step == "edit_price":
        amt = _parse_amount(text)
        if amt is None or amt <= 0:
            _say(phone, "Please send a price like *250000* or *250k*.")
            return
        p.price = amt
        db.commit()
        _clear(phone)
        _buttons(phone, f"✅ *{p.name}* price is now {naira(amt)}.",
                 [(f"adm:p:{p.id}", "Back to product"), ("adm:products", "Products"), ("adm:menu", "Admin menu")])
    else:
        m = re.search(r"\d+", text or "")
        if not m:
            _say(phone, "Please send the stock as a whole number, like *12*.")
            return
        qty = int(m.group(0))
        p.stock_quantity = qty
        if qty > 0 and p.status == "out_of_stock":
            p.status = "active"
        db.commit()
        _clear(phone)
        _buttons(phone, f"✅ *{p.name}* stock is now {qty}.",
                 [(f"adm:p:{p.id}", "Back to product"), ("adm:products", "Products"), ("adm:menu", "Admin menu")])


# ═════════════════════════════════════════════════════════════
# add-product wizard (same fields as the website form)
# ═════════════════════════════════════════════════════════════
def _start_wizard(ctx) -> None:
    _reset(ctx.phone, step="ap_name", photos=[])
    _say(ctx.phone, "➕ *New product*\n\nWhat's the product *name*? (e.g. _iPhone 15 Pro 256GB_)\nSend *cancel* any time to stop.")


def _wizard(ctx, user: User, step: str, st: Dict[str, Any], text: str, skipped: bool = False) -> None:
    phone, db = ctx.phone, ctx.db
    t = " ".join((text or "").split())

    if step in ("edit_price", "edit_stock"):
        _edit_value(ctx, user, step, st, t)
        return

    if step == "ap_name":
        if not (1 <= len(t) <= 255):
            _say(phone, "Please send the product name (up to 255 characters).")
            return
        _set(phone, step="ap_price", name=t)
        _say(phone, "💰 What's the *price* in naira? (e.g. *250000* or *250k*)")
    elif step == "ap_price":
        amt = _parse_amount(t)
        if amt is None or amt <= 0:
            _say(phone, "Please send the price as a number, like *250000* or *250k*.")
            return
        _set(phone, step="ap_category", price=str(amt))
        _ask_category(ctx)
    elif step == "ap_category":
        cat = _agent()._find_category(db, t) if t else None
        if cat is None:
            _say(phone, "I couldn't find that category. Pick one from the list, or type its name exactly.")
            _ask_category(ctx)
            return
        _wizard_category(ctx, str(cat.id), cat.name)
    elif step == "ap_stock":
        m = re.fullmatch(r"\D*(\d+)\D*", t)
        if not m:
            _say(phone, "Please send the stock quantity as a whole number, like *10*.")
            return
        _set(phone, step="ap_desc", stock=int(m.group(1)))
        _buttons(phone, "📝 Send a short *description* (specs, what's in the box, colour…), or skip it.",
                 [("adm:skip", "Skip")])
    elif step == "ap_desc":
        desc = "" if skipped else (text or "").strip()
        if len(desc) > 2000:
            _say(phone, "That's a bit long. Please keep the description under 2000 characters.")
            return
        _set(phone, step="ap_discount", desc=desc)
        _buttons(phone, "🔥 Is it on sale? Send the *discount percent* (1 to 90, e.g. *10*), or skip.",
                 [("adm:skip", "No discount")])
    elif step == "ap_discount":
        pct = None
        if not skipped:
            m = re.fullmatch(r"\D*(\d{1,2}(?:\.\d+)?)\s*%?\D*", t)
            if not m or not (0 < float(m.group(1)) <= 90):
                _say(phone, "Please send a percent between 1 and 90 (like *15*), or tap *No discount*.")
                return
            pct = float(m.group(1))
        _set(phone, step="ap_photo", discount=pct)
        _ask_photo(ctx)
    elif step == "ap_photo":
        if re.fullmatch(r"(done|finish|finished|skip|no|ok)\W*", t.lower()):
            _wizard_photos_done(ctx)
        else:
            _say(phone, "Please send the product *photo* (tap the clip 📎 → Gallery), or tap *Done* when you've sent them all.")
    elif step == "ap_confirm":
        _say(phone, "Tap *Save product* to publish it, or *Cancel*.")
    else:
        _clear(phone)
        _admin_menu(ctx, user)


def _ask_category(ctx) -> None:
    cats = ctx.db.query(Category).order_by(Category.name.asc()).all()
    if not cats:
        _say(ctx.phone, "⚠️ There are no categories yet. Please create one on the website first, then try again.")
        _clear(ctx.phone)
        return
    if len(cats) <= 10:
        shown, more = cats, False
    else:
        shown, more = cats[:9], True
    rows = [{"id": f"adm:cat:{c.id}", "title": clip(c.name, 24)} for c in shown]
    body = "🗂 Pick the *category*:"
    if more:
        body += "\n(There are more categories. You can also type a category name.)"
    _list(ctx.phone, body, "Choose category", rows, "Categories")


def _wizard_category(ctx, cat_id: str, name: Optional[str]) -> None:
    phone, db = ctx.phone, ctx.db
    if _st(phone).get("step") != "ap_category":
        _say(phone, "That list has expired. Say *add product* to start again.")
        return
    try:
        cat = db.query(Category).filter(Category.id == uuid.UUID(cat_id)).first()
    except ValueError:
        cat = None
    if cat is None:
        _say(phone, "I couldn't find that category. Please pick again.")
        _ask_category(ctx)
        return
    _set(phone, step="ap_stock", category_id=str(cat.id), category_name=cat.name)
    _say(phone, f"Category: *{cat.name}* ✅\n\n📦 How many are *in stock*? (a number)")


def _cloudinary_conf() -> Optional[Dict[str, str]]:
    url = os.environ.get("CLOUDINARY_URL", "")
    m = re.match(r"cloudinary://([^:]+):([^@]+)@(.+)", url)
    if m:
        return {"key": m.group(1), "secret": m.group(2), "cloud": m.group(3)}
    try:
        from core.config import settings

        def pick(name):
            return os.environ.get(name) or getattr(settings, name, "") or ""
    except Exception:
        def pick(name):
            return os.environ.get(name, "")
    cloud, key, secret = pick("CLOUDINARY_CLOUD_NAME"), pick("CLOUDINARY_API_KEY"), pick("CLOUDINARY_API_SECRET")
    if cloud and key and secret:
        return {"key": key, "secret": secret, "cloud": cloud}
    return None


def _upload_photo(media_id: str) -> Optional[str]:
    """WhatsApp image -> Cloudinary secure_url (the same place the website's photos live)."""
    conf = _cloudinary_conf()
    if not conf:
        return None
    got = wa.download_media(media_id)
    if not got:
        return None
    data, mime = got
    import hashlib

    import requests

    folder = os.environ.get("WHATSAPP_CLOUDINARY_FOLDER", "products")
    ts = str(int(time.time()))
    to_sign = f"folder={folder}&timestamp={ts}{conf['secret']}"
    sig = hashlib.sha1(to_sign.encode()).hexdigest()
    try:
        resp = requests.post(
            f"https://api.cloudinary.com/v1_1/{conf['cloud']}/image/upload",
            data={"api_key": conf["key"], "timestamp": ts, "folder": folder, "signature": sig},
            files={"file": ("product.jpg", data, mime or "image/jpeg")},
            timeout=60,
        )
    except requests.RequestException:
        logger.exception("Cloudinary upload failed")
        return None
    if resp.status_code >= 400:
        logger.error("Cloudinary upload failed (%s): %s", resp.status_code, resp.text[:300])
        return None
    return resp.json().get("secure_url")


def _ask_photo(ctx) -> None:
    if _cloudinary_conf() is None:
        _set(ctx.phone, step="ap_confirm")
        _say(ctx.phone, "📷 Photo upload isn't set up yet (the server needs the Cloudinary keys), so I'll "
                        "save this product without a photo. You can add the photo on the website later.")
        _confirm(ctx)
        return
    _buttons(ctx.phone, f"📷 Send the product *photo(s)* (up to {MAX_PHOTOS}). Tap *Done* when finished, or skip.",
             [("adm:done", "Done / skip")])


def _wizard_photo(ctx, user: User, media_id: str) -> None:
    phone = ctx.phone
    st = _st(phone)
    photos: List[str] = list(st.get("photos") or [])
    if len(photos) >= MAX_PHOTOS:
        _wizard_photos_done(ctx)
        return
    url = _upload_photo(media_id)
    if not url:
        _say(phone, "⚠️ I couldn't save that photo. Please send it again, or tap *Done* to continue without it.")
        return
    photos.append(url)
    _set(phone, photos=photos)
    if len(photos) >= MAX_PHOTOS:
        _wizard_photos_done(ctx)
        return
    _buttons(phone, f"📷 Photo {len(photos)} saved ✅. Send another, or tap *Done*.", [("adm:done", "Done")])


def _wizard_photos_done(ctx) -> None:
    if _st(ctx.phone).get("step") != "ap_photo":
        _say(ctx.phone, "That step has expired. Say *add product* to start again.")
        return
    _set(ctx.phone, step="ap_confirm")
    _confirm(ctx)


def _confirm(ctx) -> None:
    st = _st(ctx.phone)
    lines = ["🧾 *Please check this product*", "", f"*{st.get('name')}*",
             f"Price: {naira(st.get('price'))}"]
    if st.get("discount"):
        lines.append(f"Discount: {st['discount']}%")
    lines += [f"Category: {st.get('category_name')}", f"Stock: {st.get('stock')}",
              f"Photos: {len(st.get('photos') or [])}"]
    if st.get("desc"):
        lines.append(f"\n{clip(st['desc'], 300)}")
    _buttons(ctx.phone, "\n".join(lines), [("adm:save", "Save product"), ("adm:cancel", "Cancel")])


def _wizard_save(ctx, user: User) -> None:
    phone, db = ctx.phone, ctx.db
    st = _st(phone)
    if st.get("step") != "ap_confirm" or not st.get("name"):
        _say(phone, "That product has already been saved or the form expired. Say *add product* to start a new one.")
        return
    # claim it so a double tap can't create two copies
    if not _r().set(f"wa:adm:saving:{phone}", 1, nx=True, ex=30):
        return
    try:
        store = db.query(StoreProfile).first()
        if store is None:
            _say(phone, "⚠️ The store profile isn't configured on the server, so I can't save products.")
            return
        price = Decimal(str(st["price"]))
        pct = None
        if st.get("discount"):
            try:
                from core.discounts import normalize_discount

                pct = normalize_discount(price, discount_percent=st["discount"])
            except ValueError as exc:
                _say(phone, f"⚠️ {exc}")
                return
        product = Product(
            seller_id=store.id,
            name=st["name"],
            description=st.get("desc") or None,
            price=price,
            discount_percent=pct,
            stock_quantity=int(st.get("stock") or 0),
            category_id=uuid.UUID(st["category_id"]),
            status="active",
            amenities=[],
        )
        db.add(product)
        db.flush()
        for url in st.get("photos") or []:
            db.add(AssetImage(product_id=product.id, image_url=url))
        try:
            db.add(AuditLog(admin_id=user.id, target_id=product.id, action="product_created_whatsapp",
                            details=f"{product.name} (₦{price})"))
        except Exception:
            logger.exception("Audit log skipped")
        db.commit()
    except Exception:
        logger.exception("Saving product failed")
        try:
            db.rollback()
        except Exception:
            pass
        _say(phone, "⚠️ I couldn't save the product. Please try again in a moment.")
        return
    finally:
        _r().delete(f"wa:adm:saving:{phone}")
    _clear(phone)
    _buttons(phone, f"✅ *{product.name}* is live on the store at {naira(price)} with {int(st.get('stock') or 0)} in stock.",
             [("adm:new", "Add another"), (f"adm:p:{product.id}", "View product"), ("adm:menu", "Admin menu")])


# ═════════════════════════════════════════════════════════════
# new-order alerts (works for website, app and WhatsApp orders)
# ═════════════════════════════════════════════════════════════
_worker_started = False


def _alert_text(db, order: Order) -> str:
    buyer = order.buyer.name if order.buyer and order.buyer.name else "A customer"
    n = len(order.order_items or [])
    first = ""
    if order.order_items:
        it = order.order_items[0]
        first = f"\n{it.quantity} × {it.product.name if it.product else 'item'}" + (f" +{n - 1} more" if n > 1 else "")
    mode = "Pickup" if order.delivery_type == "pickup" else "Delivery"
    return (f"🔔 *New paid order #{str(order.id)[:8]}*\n{buyer} paid *{naira(order.total_amount)}* ({mode}).{first}")


def _send_alert(phone: str, order: Order, text: str) -> bool:
    res = wa.send_buttons(phone, text, [(f"adm:o:{order.id}", "Open order"), ("adm:menu", "Admin menu")], raw=True)
    if res is not None:
        return True
    tpl = os.environ.get("WHATSAPP_ADMIN_ALERT_TEMPLATE", "").strip()
    if not tpl:
        return False
    buyer = order.buyer.name if order.buyer and order.buyer.name else "A customer"
    res = wa._post_message({
        "to": phone,
        "type": "template",
        "template": {
            "name": tpl,
            "language": {"code": os.environ.get("WHATSAPP_ADMIN_ALERT_LANG", "en")},
            "components": [{"type": "body", "parameters": [
                {"type": "text", "text": str(order.id)[:8]},
                {"type": "text", "text": naira(order.total_amount)},
                {"type": "text", "text": buyer[:60]},
            ]}],
        },
    })
    return res is not None


def _recent_paid_clause():
    return Payment.updated_at >= func.now() - timedelta(minutes=30)


def scan_new_paid_orders() -> int:
    """One pass: alert admins about orders paid in the last 30 minutes. Returns alerts sent."""
    db = SessionLocal()
    sent = 0
    try:
        pays = (
            db.query(Payment)
            .filter(Payment.status == "completed", Payment.order_id.isnot(None), _recent_paid_clause())
            .all()
        )
        if not pays:
            return 0
        admins = db.query(WhatsAppAdminLink).filter(WhatsAppAdminLink.alerts.is_(True)).all()
        if not admins:
            return 0
        r = _r()
        for pay in pays:
            order = (
                db.query(Order)
                .options(joinedload(Order.buyer), joinedload(Order.order_items).joinedload(OrderItem.product))
                .filter(Order.id == pay.order_id)
                .first()
            )
            if order is None:
                continue
            text = _alert_text(db, order)
            for adm in admins:
                key = f"wa:adm:n:{order.id}:{adm.phone}"
                if not r.set(key, 1, nx=True, ex=7 * 86400):
                    continue
                try:
                    ok = _send_alert(adm.phone, order, text)
                except Exception:
                    logger.exception("Admin alert failed")
                    ok = False
                if ok:
                    sent += 1
                else:
                    r.delete(key)  # retry next pass (e.g. once the admin messages the bot again)
        return sent
    except Exception:
        logger.exception("Admin alert scan failed")
        return sent
    finally:
        db.close()


def start_alert_worker(interval: int = 20) -> None:
    """Background thread: check for freshly paid orders every `interval` seconds."""
    global _worker_started
    if _worker_started or os.environ.get("WHATSAPP_ADMIN_ALERTS", "true").lower() in ("0", "false", "no", "off"):
        return
    _worker_started = True

    def loop():
        time.sleep(15)
        while True:
            try:
                if _r().set("wa:adm:scan-lock", 1, nx=True, ex=max(5, interval - 2)):
                    scan_new_paid_orders()
            except Exception:
                logger.exception("Admin alert worker error")
            time.sleep(interval)

    threading.Thread(target=loop, name="wa-admin-alerts", daemon=True).start()
