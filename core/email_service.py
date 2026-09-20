import aiosmtplib
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from html import escape
from typing import Optional
from core.config import settings
import logging

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Formatting helpers
# ---------------------------------------------------------------------------

def _ngn(value) -> str:
    """Format a numeric value as Naira; pass non-numeric values through as text."""
    if value is None or value == "":
        return ""
    try:
        return f"₦{float(value):,.2f}"
    except (TypeError, ValueError):
        return str(value)


def _ref(value) -> str:
    """Short human-readable reference from a UUID/string id."""
    return str(value)[:8].upper() if value else ""


# Keys that describe internal mechanics and must never appear in a user email.
_INTERNAL_DATA_KEYS = {
    "user_id", "seller_id", "buyer_id", "updated_by", "old_status", "new_status",
    "dispute_event", "dispute_id", "resolved", "resolution", "resolution_notes",
    "context",
}

# Substrings that mark a data value as a currency amount for generic rendering.
_MONEY_KEY_HINTS = ("amount", "price", "balance", "fee", "total")


# ---------------------------------------------------------------------------
# Theme — the single source of truth for the email look.
# Edit these values (and _base_html / the shared boxes below) to restyle every
# email at once.
# ---------------------------------------------------------------------------

PAGE_BG = "#f9fafb"        # page background (gray-50)
CARD_BG = "#ffffff"        # main card
SURFACE = "#f9fafb"        # inner surfaces
BORDER = "#f3f4f6"         # hairlines (gray-100)
INK = "#111827"            # headings / strong text (gray-900)
BODY_TEXT = "#374151"      # body copy (gray-700)
MUTED = "#6b7280"          # secondary text (gray-500)
FAINT = "#9ca3af"          # labels / captions (gray-400)

BRAND = "#f97316"          # primary orange (orange-500)
BRAND_DARK = "#ea580c"     # orange-600
BRAND_SOFT = "#fff7ed"     # orange-50
BRAND_BORDER = "#fdba74"   # orange-300

SUCCESS = "#16a34a"        # green-600
DANGER = "#dc2626"         # red-600
WARNING = "#d97706"        # amber-600
INFO = "#2563eb"           # blue-600
PURPLE = "#7c3aed"         # violet-600
RADIUS = "16px"


# ---------------------------------------------------------------------------
# Shared HTML building blocks
# ---------------------------------------------------------------------------

def _detail_row(label: str, value: str, value_color: str = "") -> str:
    safe_val = escape(str(value)) if value else "—"
    color = value_color or INK
    return (
        f'<tr>'
        f'<td style="padding:9px 16px 9px 0;color:{FAINT};font-size:14px;'
        f'white-space:nowrap;vertical-align:top">{escape(label)}</td>'
        f'<td style="padding:9px 0;color:{color};font-size:14px;'
        f'font-weight:600;text-align:right">{safe_val}</td>'
        f'</tr>'
    )


def _details_card(rows: list[tuple[str, str]], accent: str = BRAND) -> str:
    rows_html = "".join(_detail_row(k, v) for k, v in rows if v)
    return (
        f'<div style="background:{CARD_BG};border:1px solid {BORDER};'
        f'border-left:4px solid {accent};border-radius:14px;padding:14px 20px;margin:20px 0">'
        f'<table style="width:100%;border-collapse:collapse">'
        f'{rows_html}'
        f'</table></div>'
    )


def _alert_box(text: str, color: str = DANGER) -> str:
    return (
        f'<div style="background:{color}14;border-left:4px solid {color};'
        f'border-radius:12px;padding:14px 18px;margin:18px 0">'
        f'<p style="color:{INK};margin:0;font-size:14px;line-height:1.55">'
        f'{escape(text)}</p></div>'
    )


def _info_box(text: str, color: str = BRAND) -> str:
    return (
        f'<div style="background:{color}12;border:1px solid {color}40;'
        f'border-radius:12px;padding:16px 18px;margin:18px 0;text-align:center">'
        f'<p style="color:{INK};margin:0;font-size:15px;font-weight:600">'
        f'{escape(text)}</p></div>'
    )


def _badge_html(icon: str, header_bg: str) -> str:
    """Default circular icon badge used in the header, tinted per event."""
    return (
        f'<div style="width:64px;height:64px;border-radius:9999px;background:{header_bg};'
        f'line-height:64px;font-size:28px;text-align:center;margin:0 auto;'
        f'box-shadow:0 8px 20px rgba(249,115,22,.16)">{icon}</div>'
    )


def _brand_row(from_name: str) -> str:
    letter = escape((from_name or "L").strip()[:1].upper())
    return (
        f'<table cellpadding="0" cellspacing="0" role="presentation"><tr>'
        f'<td style="width:36px;height:36px;background:{BRAND};border-radius:12px;'
        f'text-align:center;vertical-align:middle;color:#ffffff;font-size:17px;'
        f'font-weight:800">{letter}</td>'
        f'<td style="padding-left:10px;font-size:16px;font-weight:700;color:{INK}">'
        f'{escape(from_name)}</td></tr></table>'
    )


def _base_html(
    *,
    from_name: str,
    icon: str,
    header_bg: str,
    header_fg: str = "",
    header_title: str,
    header_subtitle: str = "",
    greeting: str,
    body_html: str,
    footer_note: str = "",
    badge_html: str = "",
    cta_html: str = "",
) -> str:
    footer_note_html = (
        f'<p style="color:{FAINT};font-size:12px;margin:8px 0 0">'
        f'{escape(footer_note)}</p>'
        if footer_note else ""
    )
    badge = badge_html or _badge_html(icon, header_bg)
    subtitle_html = (
        f'<div style="font-size:14px;color:{MUTED};margin-top:6px">'
        f'{escape(header_subtitle)}</div>'
        if header_subtitle else ""
    )
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width,initial-scale=1.0">
  <title>{escape(header_title)}</title>
</head>
<body style="margin:0;padding:0;background:{PAGE_BG};font-family:-apple-system,'Segoe UI',Roboto,Helvetica,Arial,sans-serif">
  <table width="100%" cellpadding="0" cellspacing="0" style="background:{PAGE_BG};padding:28px 12px">
    <tr><td align="center">
      <table width="600" cellpadding="0" cellspacing="0"
             style="max-width:600px;width:100%;background:{CARD_BG};border-radius:20px;
                    overflow:hidden;border:1px solid {BORDER};
                    box-shadow:0 1px 3px rgba(17,24,39,.08)">

        <!-- BRAND -->
        <tr>
          <td style="padding:20px 24px 0">{_brand_row(from_name)}</td>
        </tr>

        <!-- HEADER BADGE + TITLE -->
        <tr>
          <td style="padding:22px 32px 0;text-align:center">
            {badge}
            <div style="font-size:22px;font-weight:800;color:{INK};letter-spacing:-.4px;
                        margin-top:16px">{escape(header_title)}</div>
            {subtitle_html}
          </td>
        </tr>

        <!-- BODY -->
        <tr>
          <td style="padding:20px 32px 8px">
            <p style="color:{INK};font-size:16px;margin:0 0 16px;font-weight:600">
              {escape(greeting)}</p>
            {body_html}
          </td>
        </tr>

        {cta_html}

        <!-- FOOTER -->
        <tr>
          <td style="padding:24px 32px 28px;text-align:center;border-top:1px solid {BORDER}">
            <p style="color:{FAINT};font-size:12px;margin:0">
              © {escape(from_name)} &nbsp;·&nbsp; All rights reserved</p>
            {footer_note_html}
          </td>
        </tr>

      </table>
    </td></tr>
  </table>
</body>
</html>"""


def _base_text(*, from_name: str, title: str, greeting: str, body: str, footer: str = "") -> str:
    sep = "─" * 60
    return f"""{from_name} — {title}
{sep}

{greeting}

{body}
{sep}
© {from_name}
{footer}"""


# ---------------------------------------------------------------------------
# EmailService
# ---------------------------------------------------------------------------

class EmailService:

    def __init__(self):
        self.smtp_host = settings.SMTP_HOST
        self.smtp_port = settings.SMTP_PORT
        self.username = settings.SMTP_USERNAME
        self.password = settings.SMTP_PASSWORD
        self.use_tls = settings.SMTP_USE_TLS
        self.use_ssl = settings.SMTP_USE_SSL
        self.from_email = settings.FROM_EMAIL or settings.SMTP_USERNAME
        self.from_name = settings.FROM_NAME

    # ── Transport ──────────────────────────────────────────────────────────

    def _create_message(self, to_email, subject, html_body, text_body=None):
        msg = MIMEMultipart("alternative")
        msg["Subject"] = subject
        msg["From"] = f"{self.from_name} <{self.from_email}>"
        msg["To"] = to_email
        if text_body:
            msg.attach(MIMEText(text_body, "plain"))
        msg.attach(MIMEText(html_body, "html"))
        return msg

    async def send_email_async(self, to_email, subject, html_body, text_body=None) -> bool:
        try:
            msg = self._create_message(to_email, subject, html_body, text_body)
            if self.use_ssl:
                # Port 465 — SSL from the start
                smtp = aiosmtplib.SMTP(hostname=self.smtp_host, port=self.smtp_port,
                                       use_tls=True, timeout=30)
            else:
                # Port 587 — aiosmtplib v4 auto-performs STARTTLS on connect
                # when the server announces it; do not call starttls() manually
                smtp = aiosmtplib.SMTP(hostname=self.smtp_host, port=self.smtp_port,
                                       use_tls=False, timeout=30)
            await smtp.connect()
            if self.username and self.password:
                await smtp.login(self.username, self.password)
            await smtp.send_message(msg)
            await smtp.quit()
            logger.info(f"Email sent to {to_email}")
            return True
        except Exception as e:
            logger.error(f"Failed to send email to {to_email}: {e}")
            return False

    def send_email_sync(self, to_email, subject, html_body, text_body=None) -> bool:
        try:
            msg = self._create_message(to_email, subject, html_body, text_body)
            if self.use_ssl:
                server = smtplib.SMTP_SSL(self.smtp_host, self.smtp_port, timeout=30)
            else:
                server = smtplib.SMTP(self.smtp_host, self.smtp_port, timeout=30)
                if self.use_tls:
                    server.starttls()
            server.set_debuglevel(0)
            if self.username and self.password:
                server.login(self.username, self.password)
            server.send_message(msg)
            server.quit()
            logger.info(f"Email sent to {to_email}")
            return True
        except Exception as e:
            logger.error(f"Failed to send email to {to_email}: {e}")
            return False

    # ── Templates ──────────────────────────────────────────────────────────

    def render_verification_email(self, user_name: str, verification_code: str) -> tuple[str, str]:
        expire = settings.EMAIL_VERIFICATION_EXPIRE_MINUTES
        body = (
            f'<p style="color:#374151;font-size:15px;line-height:1.6;margin:0 0 20px">'
            f'Thank you for joining <strong>{escape(self.from_name)}</strong>! '
            f'Enter the code below to verify your email address and activate your account.</p>'
            f'<div style="background:#fff7ed;border:2px solid #f97316;border-radius:16px;'
            f'padding:32px;text-align:center;margin:24px 0;'
            f'box-shadow:0 8px 24px rgba(249,115,22,.12)">'
            f'<p style="color:#9ca3af;font-size:12px;text-transform:uppercase;'
            f'letter-spacing:2px;margin:0 0 12px">Verification Code</p>'
            f'<div style="font-size:40px;font-weight:900;letter-spacing:12px;color:#ea580c;'
            f'font-family:monospace">{escape(verification_code)}</div>'
            f'<p style="color:#9ca3af;font-size:13px;margin:12px 0 0">Expires in {expire} minutes</p>'
            f'</div>'
            + _alert_box("Do not share this code with anyone. "
                         "If you didn't request this, please ignore this email.")
        )
        html = _base_html(
            from_name=self.from_name, icon="✉️",
            header_bg="linear-gradient(135deg,#FFD700,#FFA500)",
            header_fg="#000",
            header_title="Email Verification",
            header_subtitle="Confirm your email address",
            greeting=f"Hello {user_name},",
            body_html=body,
        )
        text = _base_text(
            from_name=self.from_name, title="Email Verification",
            greeting=f"Hello {user_name},",
            body=(f"Verification Code: {verification_code}\n"
                  f"Expires in {expire} minutes.\n\n"
                  f"Do not share this code with anyone."),
        )
        return html, text

    def render_password_reset_email(self, user_name: str, reset_code: str) -> tuple[str, str]:
        expire = settings.PASSWORD_RESET_EXPIRE_MINUTES
        body = (
            f'<p style="color:#374151;font-size:15px;line-height:1.6;margin:0 0 20px">'
            f'We received a request to reset your password. '
            f'Use the code below to create a new password.</p>'
            f'<div style="background:#fef2f2;border:2px solid #ef4444;border-radius:16px;'
            f'padding:32px;text-align:center;margin:24px 0;'
            f'box-shadow:0 8px 24px rgba(239,68,68,.12)">'
            f'<p style="color:#9ca3af;font-size:12px;text-transform:uppercase;'
            f'letter-spacing:2px;margin:0 0 12px">Reset Code</p>'
            f'<div style="font-size:40px;font-weight:900;letter-spacing:12px;color:#dc2626;'
            f'font-family:monospace">{escape(reset_code)}</div>'
            f'<p style="color:#9ca3af;font-size:13px;margin:12px 0 0">Expires in {expire} minutes</p>'
            f'</div>'
            + _alert_box("If you didn't request a password reset, "
                         "your account is safe — just ignore this email.", "#ff6b6b")
        )
        html = _base_html(
            from_name=self.from_name, icon="🔑",
            header_bg="linear-gradient(135deg,#c0392b,#e74c3c)",
            header_fg="#fff",
            header_title="Password Reset",
            header_subtitle="Reset your account password",
            greeting=f"Hello {user_name},",
            body_html=body,
        )
        text = _base_text(
            from_name=self.from_name, title="Password Reset",
            greeting=f"Hello {user_name},",
            body=(f"Reset Code: {reset_code}\n"
                  f"Expires in {expire} minutes.\n\n"
                  f"If you didn't request this, ignore this email."),
        )
        return html, text

    def render_welcome_email(self, user_name: str) -> tuple[str, str]:
        body = (
            f'<p style="color:#374151;font-size:15px;line-height:1.6;margin:0 0 16px">'
            f'Welcome to <strong>{escape(self.from_name)}</strong>! '
            f'Your email has been verified and your account is ready to use.</p>'
            + _info_box("🎉 Your account is now active!")
            + f'<p style="color:#6b7280;font-size:14px;line-height:1.6;margin:16px 0 0">'
            f'Explore the marketplace to buy and sell vehicles, properties, and more. '
            f'If you have any questions, our support team is always here to help.</p>'
        )
        html = _base_html(
            from_name=self.from_name, icon="🌟",
            header_bg="linear-gradient(135deg,#FFD700,#FFA500)",
            header_fg="#000",
            header_title="Welcome Aboard!",
            header_subtitle="Your account is verified and ready",
            greeting=f"Hello {user_name},",
            body_html=body,
        )
        text = _base_text(
            from_name=self.from_name, title="Welcome!",
            greeting=f"Hello {user_name},",
            body=(f"Welcome to {self.from_name}!\n\n"
                  f"Your email has been verified. Your account is now active."),
        )
        return html, text

    def render_login_email(self, user_name: str, login_time: str,
                           ip_address: Optional[str] = None,
                           device: Optional[str] = None) -> tuple[str, str]:
        rows: list[tuple[str, str]] = [("Time", login_time)]
        if ip_address:
            rows.append(("IP Address", ip_address))
        if device:
            rows.append(("Device", device))

        body = (
            f'<p style="color:#374151;font-size:15px;line-height:1.6;margin:0 0 20px">'
            f'A new sign-in was detected on your <strong>{escape(self.from_name)}</strong> account.</p>'
            + _details_card(rows, "#4a9eff")
            + _alert_box(
                "If this wasn't you, please change your password immediately "
                "and contact our support team.", "#ff6b6b"
            )
        )
        html = _base_html(
            from_name=self.from_name, icon="🔐",
            header_bg="linear-gradient(135deg,#1a1a2e,#16213e)",
            header_fg="#4a9eff",
            header_title="New Sign-In Detected",
            header_subtitle="Someone just signed in to your account",
            greeting=f"Hello {user_name},",
            body_html=body,
            footer_note="This email was sent for your security. We never ask for your password.",
        )
        detail_text = "\n".join(f"{k}: {v}" for k, v in rows)
        text = _base_text(
            from_name=self.from_name, title="New Sign-In",
            greeting=f"Hello {user_name},",
            body=(f"A new sign-in was detected on your account.\n\n"
                  f"{detail_text}\n\n"
                  f"If this wasn't you, change your password immediately."),
        )
        return html, text

    def render_inspection_confirmed_email(self, user_name: str, asset_title: str,
                                           inspection_date: str, location: Optional[str],
                                           seller_name: str,
                                           seller_contact: Optional[str] = None) -> tuple[str, str]:
        rows = [
            ("Asset", asset_title),
            ("Seller", seller_name),
            ("Date & Time", inspection_date),
        ]
        if location:
            rows.append(("Location", location))
        if seller_contact:
            rows.append(("Seller Contact", seller_contact))

        body = (
            f'<p style="color:#374151;font-size:15px;line-height:1.6;margin:0 0 20px">'
            f'Your inspection request has been confirmed by the seller. '
            f'Please be present at the agreed time.</p>'
            + _details_card(rows, "#3498db")
            + _info_box("Please arrive on time. Bring a valid ID for verification.", "#3498db")
        )
        html = _base_html(
            from_name=self.from_name, icon="📅",
            header_bg="linear-gradient(135deg,#1a5276,#2e86c1)",
            header_fg="#fff",
            header_title="Inspection Confirmed",
            header_subtitle="Your physical inspection is scheduled",
            greeting=f"Hello {escape(user_name)},",
            body_html=body,
        )
        text = _base_text(
            from_name=self.from_name, title="Inspection Confirmed",
            greeting=f"Hello {user_name},",
            body="\n".join(f"{k}: {v}" for k, v in rows),
        )
        return html, text

    def render_agreement_created_email(self, seller_name: str, buyer_name: str,
                                        asset_title: str, total_price: str,
                                        deposit: str, plan_type: str,
                                        monthly: Optional[str] = None,
                                        duration: Optional[str] = None) -> tuple[str, str]:
        rows = [
            ("Asset", asset_title),
            ("Buyer", buyer_name),
            ("Total Price", total_price),
            ("Deposit Required", deposit),
            ("Plan Type", plan_type.replace("_", " ").title()),
        ]
        if monthly:
            rows.append(("Monthly Installment", monthly))
        if duration:
            rows.append(("Duration", duration))

        body = (
            f'<p style="color:#374151;font-size:15px;line-height:1.6;margin:0 0 20px">'
            f'A new purchase agreement has been created for <strong>{escape(asset_title)}</strong>. '
            f'The buyer needs to pay the deposit to activate the agreement.</p>'
            + _details_card(rows, "#8e44ad")
            + _info_box("The agreement becomes active once the buyer pays the deposit.", "#8e44ad")
        )
        html = _base_html(
            from_name=self.from_name, icon="📄",
            header_bg="linear-gradient(135deg,#6c3483,#8e44ad)",
            header_fg="#fff",
            header_title="Agreement Created",
            header_subtitle="New purchase agreement pending deposit",
            greeting=f"Hello {escape(seller_name)},",
            body_html=body,
        )
        text = _base_text(
            from_name=self.from_name, title="New Agreement Created",
            greeting=f"Hello {seller_name},",
            body="\n".join(f"{k}: {v}" for k, v in rows),
        )
        return html, text

    def render_agreement_approved_email(self, user_name: str, asset_title: str,
                                         total_price: str, remaining: str,
                                         next_due: Optional[str] = None,
                                         monthly: Optional[str] = None,
                                         reference: Optional[str] = None) -> tuple[str, str]:
        rows = [
            ("Asset", asset_title),
            ("Total Price", total_price),
            ("Remaining Balance", remaining),
        ]
        if monthly:
            rows.append(("Monthly Installment", monthly))
        if next_due:
            rows.append(("Next Payment Due", next_due))
        if reference:
            rows.append(("Reference", reference))

        body = (
            f'<p style="color:#374151;font-size:15px;line-height:1.6;margin:0 0 20px">'
            f'Your purchase agreement for <strong>{escape(asset_title)}</strong> has been '
            f'approved. Pay your deposit to activate it.</p>'
            + _details_card(rows, "#f39c12")
            + _info_box("Your agreement activates once your deposit is confirmed.", "#f39c12")
        )
        html = _base_html(
            from_name=self.from_name, icon="🤝",
            header_bg="linear-gradient(135deg,#7d3c00,#f39c12)",
            header_fg="#fff",
            header_title="Agreement Approved",
            header_subtitle="Deposit required to activate",
            greeting=f"Hello {escape(user_name)},",
            body_html=body,
        )
        text = _base_text(
            from_name=self.from_name, title="Agreement Approved — Deposit Required",
            greeting=f"Hello {user_name},",
            body=("Your agreement has been approved. Pay your deposit to activate it.\n\n"
                  + "\n".join(f"{k}: {v}" for k, v in rows)
                  + "\n\nYour agreement activates once your deposit is confirmed."),
        )
        return html, text

    def render_agreement_activated_email(self, user_name: str, asset_title: str,
                                          total_price, amount_paid, remaining,
                                          monthly=None, next_due: Optional[str] = None,
                                          reference: Optional[str] = None) -> tuple[str, str]:
        rows = [
            ("Asset", asset_title),
            ("Total Price", _ngn(total_price)),
            ("Deposit Paid", _ngn(amount_paid)),
            ("Remaining Balance", _ngn(remaining)),
        ]
        if monthly:
            rows.append(("Monthly Installment", _ngn(monthly)))
        if next_due:
            rows.append(("Next Payment Due", next_due))
        if reference:
            rows.append(("Reference", reference))

        body = (
            f'<p style="color:#374151;font-size:15px;line-height:1.6;margin:0 0 20px">'
            f'Your deposit for <strong>{escape(asset_title)}</strong> has been confirmed and '
            f'your agreement is now active.</p>'
            + _details_card(rows, "#27ae60")
            + _info_box("Keep up with your payments to complete the purchase.", "#27ae60")
        )
        html = _base_html(
            from_name=self.from_name, icon="✅",
            header_bg="linear-gradient(135deg,#1e8449,#27ae60)",
            header_fg="#fff",
            header_title="Agreement Activated",
            header_subtitle="Your installment plan has started",
            greeting=f"Hello {escape(user_name)},",
            body_html=body,
        )
        text = _base_text(
            from_name=self.from_name, title="Agreement Activated",
            greeting=f"Hello {user_name},",
            body="\n".join(f"{k}: {v}" for k, v in rows),
        )
        return html, text

    def render_financing_application_approved_email(self, user_name: str,
                                                     reference: Optional[str] = None,
                                                     reviewed_on: Optional[str] = None) -> tuple[str, str]:
        rows = []
        if reference:
            rows.append(("Reference", reference))
        if reviewed_on:
            rows.append(("Reviewed On", reviewed_on))

        body = (
            f'<p style="color:#374151;font-size:15px;line-height:1.6;margin:0 0 20px">'
            f'Good news - your financing application has been reviewed and approved. '
            f'You can now select a monthly or installment plan on any purchase.</p>'
            + (_details_card(rows, "#27ae60") if rows else "")
            + _info_box("Head back to your purchase and choose your preferred plan at checkout.", "#27ae60")
            + f'<p style="color:#6b7280;font-size:14px;line-height:1.6;margin:16px 0 0">'
            f'Next steps: open the asset you inspected, select Monthly or Installment, and '
            f'pay the deposit (or first installment) to activate your plan.</p>'
        )
        html = _base_html(
            from_name=self.from_name, icon="✅",
            header_bg="linear-gradient(135deg,#1e8449,#27ae60)",
            header_fg="#fff",
            header_title="Financing Application Approved",
            header_subtitle="You're eligible for monthly and installment plans",
            greeting=f"Hello {escape(user_name)},",
            body_html=body,
        )
        text = _base_text(
            from_name=self.from_name, title="Financing Application Approved",
            greeting=f"Hello {user_name},",
            body=("Your financing application has been approved. You can now select a monthly "
                  "or installment plan on any purchase.\n\n"
                  + "\n".join(f"{k}: {v}" for k, v in rows)
                  + "\n\nNext steps: choose your preferred plan at checkout and pay the deposit "
                  "(or first installment) to activate it."),
        )
        return html, text

    def render_financing_application_rejected_email(self, user_name: str, reason: str,
                                                     reference: Optional[str] = None,
                                                     decision_date: Optional[str] = None) -> tuple[str, str]:
        rows = [("Reason", reason)]
        if reference:
            rows.append(("Reference", reference))
        if decision_date:
            rows.append(("Decision Date", decision_date))
        body = (
            f'<p style="color:#374151;font-size:15px;line-height:1.6;margin:0 0 20px">'
            f'Your financing application was not approved this time.</p>'
            + _details_card(rows, "#c0392b")
            + _info_box("You may submit a new application at any time.", "#c0392b")
            + f'<p style="color:#6b7280;font-size:14px;line-height:1.6;margin:16px 0 0">'
            f'You can reapply with updated documents or contact support if you believe this '
            f'decision was made in error.</p>'
        )
        html = _base_html(
            from_name=self.from_name, icon="✖️",
            header_bg="linear-gradient(135deg,#922b21,#c0392b)",
            header_fg="#fff",
            header_title="Financing Application Rejected",
            header_subtitle="Your application was not approved",
            greeting=f"Hello {escape(user_name)},",
            body_html=body,
        )
        text = _base_text(
            from_name=self.from_name, title="Financing Application Rejected",
            greeting=f"Hello {user_name},",
            body="\n".join(f"{k}: {v}" for k, v in rows),
        )
        return html, text

    def render_financing_application_revoked_email(self, user_name: str, reason: str,
                                                    reference: Optional[str] = None,
                                                    decision_date: Optional[str] = None) -> tuple[str, str]:
        rows = [("Reason", reason)]
        if reference:
            rows.append(("Reference", reference))
        if decision_date:
            rows.append(("Revoked On", decision_date))
        body = (
            f'<p style="color:#374151;font-size:15px;line-height:1.6;margin:0 0 20px">'
            f'Your financing eligibility has been revoked. You will need to submit a new '
            f'application before selecting a monthly or installment plan again.</p>'
            + _details_card(rows, "#c0392b")
            + f'<p style="color:#6b7280;font-size:14px;line-height:1.6;margin:16px 0 0">'
            f'To regain eligibility, submit a new application through your account. '
            f'Contact support if you need help.</p>'
        )
        html = _base_html(
            from_name=self.from_name, icon="⚠️",
            header_bg="linear-gradient(135deg,#922b21,#c0392b)",
            header_fg="#fff",
            header_title="Financing Eligibility Revoked",
            header_subtitle="Your financing eligibility has changed",
            greeting=f"Hello {escape(user_name)},",
            body_html=body,
        )
        text = _base_text(
            from_name=self.from_name, title="Financing Eligibility Revoked",
            greeting=f"Hello {user_name},",
            body="\n".join(f"{k}: {v}" for k, v in rows),
        )
        return html, text

    def render_installment_reminder_email(self, user_name: str, asset_title: str,
                                           amount_due: str, due_date: str,
                                           days_left: int,
                                           remaining_balance: Optional[str] = None) -> tuple[str, str]:
        rows = [
            ("Asset", asset_title),
            ("Amount Due", amount_due),
            ("Due Date", due_date),
            ("Days Remaining", str(days_left)),
        ]
        if remaining_balance:
            rows.append(("Remaining Balance After", remaining_balance))

        urgency_color = "#e74c3c" if days_left <= 3 else "#e67e22" if days_left <= 5 else "#f39c12"
        body = (
            f'<p style="color:#374151;font-size:15px;line-height:1.6;margin:0 0 20px">'
            f'Your installment payment for <strong>{escape(asset_title)}</strong> is due '
            f'in <strong style="color:{urgency_color}">{days_left} day{"s" if days_left != 1 else ""}</strong>. '
            f'Please ensure your payment is made on time to keep your agreement active.</p>'
            + _details_card(rows, urgency_color)
            + _alert_box(
                "Missing payments may result in agreement default and loss of your deposit.",
                urgency_color
            )
        )
        html = _base_html(
            from_name=self.from_name, icon="⏰",
            header_bg=f"linear-gradient(135deg,#7d3c00,{urgency_color})",
            header_fg="#fff",
            header_title="Installment Payment Reminder",
            header_subtitle=f"Payment due in {days_left} day{'s' if days_left != 1 else ''}",
            greeting=f"Hello {escape(user_name)},",
            body_html=body,
        )
        text = _base_text(
            from_name=self.from_name, title="Installment Reminder",
            greeting=f"Hello {user_name},",
            body="\n".join(f"{k}: {v}" for k, v in rows),
        )
        return html, text

    def render_dispute_opened_email(self, user_name: str, dispute_title: str,
                                     reference: str,
                                     order_or_agreement_id: Optional[str] = None) -> tuple[str, str]:
        rows = [
            ("Dispute Title", dispute_title),
            ("Reference", reference),
        ]
        if order_or_agreement_id:
            rows.append(("Order/Agreement", order_or_agreement_id[:8].upper()))

        body = (
            f'<p style="color:#374151;font-size:15px;line-height:1.6;margin:0 0 20px">'
            f'A dispute has been opened and is now under review by our team. '
            f'We will investigate and respond within 2–3 business days.</p>'
            + _details_card(rows, "#e67e22")
            + _info_box("You will be notified when a resolution is reached.", "#e67e22")
        )
        html = _base_html(
            from_name=self.from_name, icon="⚖️",
            header_bg="linear-gradient(135deg,#784212,#ca6f1e)",
            header_fg="#fff",
            header_title="Dispute Opened",
            header_subtitle="Under review — we'll resolve this for you",
            greeting=f"Hello {escape(user_name)},",
            body_html=body,
        )
        text = _base_text(
            from_name=self.from_name, title="Dispute Opened",
            greeting=f"Hello {user_name},",
            body="\n".join(f"{k}: {v}" for k, v in rows),
        )
        return html, text

    def render_dispute_resolved_email(self, user_name: str, dispute_title: str,
                                       resolution: str,
                                       notes: Optional[str] = None) -> tuple[str, str]:
        rows = [
            ("Dispute", dispute_title),
            ("Resolution", resolution.replace("_", " ").title()),
        ]
        if notes:
            rows.append(("Notes", notes))

        body = (
            f'<p style="color:#374151;font-size:15px;line-height:1.6;margin:0 0 20px">'
            f'Your dispute has been reviewed and a resolution has been reached.</p>'
            + _details_card(rows, "#27ae60")
            + _info_box("Thank you for your patience during this process.", "#27ae60")
        )
        html = _base_html(
            from_name=self.from_name, icon="✅",
            header_bg="linear-gradient(135deg,#1e8449,#27ae60)",
            header_fg="#fff",
            header_title="Dispute Resolved",
            header_subtitle="A resolution has been reached",
            greeting=f"Hello {escape(user_name)},",
            body_html=body,
        )
        text = _base_text(
            from_name=self.from_name, title="Dispute Resolved",
            greeting=f"Hello {user_name},",
            body="\n".join(f"{k}: {v}" for k, v in rows),
        )
        return html, text

    def render_order_shipped_email(self, user_name: str, order_id: str,
                                    items_summary: str,
                                    total: str,
                                    tracking_note: Optional[str] = None) -> tuple[str, str]:
        rows = [
            ("Order ID", f"#{order_id[:8].upper()}"),
            ("Items", items_summary),
            ("Total", total),
        ]
        body = (
            f'<p style="color:#374151;font-size:15px;line-height:1.6;margin:0 0 20px">'
            f'Your order has been dispatched and is on its way to you!</p>'
            + _details_card(rows, "#3498db")
            + _info_box(
                tracking_note or "Delivery fees are included in your order total when applicable.",
                "#3498db"
            )
        )
        html = _base_html(
            from_name=self.from_name, icon="🚚",
            header_bg="linear-gradient(135deg,#1a5276,#2e86c1)",
            header_fg="#fff",
            header_title="Order Shipped",
            header_subtitle="Your order is on its way",
            greeting=f"Hello {escape(user_name)},",
            body_html=body,
        )
        text = _base_text(
            from_name=self.from_name, title="Order Shipped",
            greeting=f"Hello {user_name},",
            body="\n".join(f"{k}: {v}" for k, v in rows),
        )
        return html, text

    def render_order_delivered_email(self, user_name: str, order_id: str,
                                      items_summary: str, total: str) -> tuple[str, str]:
        rows = [
            ("Order ID", f"#{order_id[:8].upper()}"),
            ("Items", items_summary),
            ("Total Paid", total),
        ]
        body = (
            f'<p style="color:#374151;font-size:15px;line-height:1.6;margin:0 0 20px">'
            f'Your order has been delivered. We hope you\'re happy with your purchase!</p>'
            + _details_card(rows, "#27ae60")
            + _info_box("Enjoying your purchase? Leave a review for the seller.", "#27ae60")
        )
        html = _base_html(
            from_name=self.from_name, icon="📦",
            header_bg="linear-gradient(135deg,#1e8449,#27ae60)",
            header_fg="#fff",
            header_title="Order Delivered",
            header_subtitle="Your purchase has arrived",
            greeting=f"Hello {escape(user_name)},",
            body_html=body,
        )
        text = _base_text(
            from_name=self.from_name, title="Order Delivered",
            greeting=f"Hello {user_name},",
            body="\n".join(f"{k}: {v}" for k, v in rows),
        )
        return html, text

    def render_order_confirmed_email(self, user_name: str, order_id: str,
                                      items_summary: str, total,
                                      delivery_type: str = "delivery",
                                      delivery_fee=None,
                                      estimated_delivery: Optional[str] = None,
                                      subtotal=None, discount=None,
                                      delivery_city: Optional[str] = None,
                                      order_date: Optional[str] = None,
                                      order_time: Optional[str] = None,
                                      items: Optional[list] = None) -> tuple[str, str]:
        order_ref = f"#{order_id[:8].upper()}" if order_id else "N/A"
        delivery_label = delivery_type.replace("_", " ").title() if delivery_type else "—"

        # ── Success badge ───────────────────────────────────────────────
        badge_html = (
            f'<div style="width:64px;height:64px;border-radius:9999px;background:#dcfce7;'
            f'border:3px solid {SUCCESS};line-height:58px;text-align:center;'
            f'font-size:28px;color:{SUCCESS};margin:0 auto">✓</div>'
        )

        # ── Order summary card ──────────────────────────────────────────
        def _row(label, value, value_color=None, weight="600"):
            color = value_color or INK
            return (
                f'<tr>'
                f'<td style="padding:7px 0;color:{FAINT};font-size:14px">{escape(label)}</td>'
                f'<td style="padding:7px 0;color:{color};font-size:14px;font-weight:{weight};'
                f'text-align:right">{value}</td></tr>'
            )

        summary_rows = ""
        if subtotal is not None:
            summary_rows += _row("Subtotal", _ngn(subtotal))
        delivery_dest = f" ({delivery_city})" if delivery_city else ""
        summary_rows += _row(f"Delivery{delivery_dest}", _ngn(delivery_fee) if delivery_fee else "—")
        if discount:
            summary_rows += _row("Spend & save discount", f"-{_ngn(discount)}", SUCCESS)
        total_html = (
            f'<tr><td colspan="2" style="padding:0"><div style="border-top:1px solid {BORDER};'
            f'margin:8px 0"></div></td></tr>'
            f'<tr><td style="padding:7px 0;color:{INK};font-size:16px;font-weight:700">Total</td>'
            f'<td style="padding:7px 0;color:{BRAND};font-size:16px;font-weight:800;'
            f'text-align:right">{_ngn(total)}</td></tr>'
        )
        summary_card = (
            f'<div style="background:{CARD_BG};border:1px solid {BORDER};border-radius:16px;'
            f'padding:18px 20px;margin:0 0 16px">'
            f'<div style="font-size:17px;font-weight:800;color:{INK};margin-bottom:8px">'
            f'Order summary</div>'
            f'<table style="width:100%;border-collapse:collapse">{summary_rows}{total_html}</table>'
            f'</div>'
        )

        # ── Order details card ──────────────────────────────────────────
        def _detail(label, value, value_color=None):
            color = value_color or INK
            return (
                f'<tr><td style="padding:6px 0;color:{FAINT};font-size:14px">{escape(label)}</td>'
                f'<td style="padding:6px 0;color:{color};font-size:14px;font-weight:600;'
                f'text-align:right">{value}</td></tr>'
            )

        details_rows = _detail("Order Number", escape(order_ref))
        if order_date:
            details_rows += _detail("Order Date", escape(order_date))
        if order_time:
            details_rows += _detail("Order Time", escape(order_time), SUCCESS)
        if estimated_delivery:
            details_rows += _detail("Estimated Delivery", escape(estimated_delivery))
        if not (items or []) and items_summary:
            details_rows += _detail("Items", escape(items_summary))
        details_card = (
            f'<div style="background:{CARD_BG};border:1px solid {BORDER};border-radius:16px;'
            f'padding:18px 20px;margin:0 0 16px">'
            f'<table style="width:100%;border-collapse:collapse">{details_rows}</table></div>'
        )

        # ── Items card ──────────────────────────────────────────────────
        items_card = ""
        item_list = items or []
        if item_list:
            rows_html = ""
            last = len(item_list) - 1
            for idx, item in enumerate(item_list):
                name = escape(str(item.get("name") or "Item"))
                variant = item.get("variant")
                price = item.get("price")
                image = item.get("image")
                border = "" if idx == last else f"border-bottom:1px solid {BORDER};"
                if image and str(image).startswith("http"):
                    thumb = (f'<img src="{escape(str(image))}" width="56" height="56" '
                             f'style="border-radius:12px;object-fit:cover;background:{SURFACE}" alt="">')
                else:
                    thumb = (f'<div style="width:56px;height:56px;border-radius:12px;'
                             f'background:{SURFACE};border:1px solid {BORDER}"></div>')
                variant_html = (
                    f'<div style="color:{FAINT};font-size:13px;margin:3px 0">{escape(str(variant))}</div>'
                    if variant else ""
                )
                price_html = (
                    f'<div style="color:{BRAND};font-size:14px;font-weight:700">{_ngn(price)}</div>'
                    if price is not None else ""
                )
                rows_html += (
                    f'<tr>'
                    f'<td style="width:56px;padding:14px 0;{border}vertical-align:top">{thumb}</td>'
                    f'<td style="padding:14px 0 14px 12px;{border}vertical-align:top">'
                    f'<div style="color:{INK};font-size:14px;font-weight:600;line-height:1.4">{name}</div>'
                    f'{variant_html}{price_html}</td></tr>'
                )
            items_card = (
                f'<div style="background:{CARD_BG};border:1px solid {BORDER};border-radius:16px;'
                f'padding:4px 20px;margin:0 0 16px">'
                f'<table style="width:100%;border-collapse:collapse">{rows_html}</table></div>'
            )

        intro = (
            f'<p style="color:{MUTED};font-size:15px;line-height:1.6;margin:0 0 4px">'
            f'Thank you for shopping with {escape(self.from_name)}.</p>'
            f'<p style="color:{MUTED};font-size:15px;line-height:1.6;margin:0 0 20px">'
            f'Your order has been received and it\'s being prepared.</p>'
        )

        body = intro + summary_card + details_card + items_card

        cta_html = (
            f'<tr><td style="padding:8px 32px 28px">'
            f'<a href="#" style="display:block;background:{BRAND};color:#ffffff;text-decoration:none;'
            f'text-align:center;font-size:16px;font-weight:700;padding:15px 0;border-radius:9999px">'
            f'View Order</a></td></tr>'
        )

        html = _base_html(
            from_name=self.from_name, icon="✓",
            header_bg=f"linear-gradient(135deg,{BRAND},{BRAND_DARK})",
            header_title="Your Order is on the Way",
            header_subtitle="",
            greeting=f"Hi {user_name},",
            body_html=body,
            badge_html=badge_html,
            cta_html=cta_html,
        )

        summary_text_rows = []
        if subtotal is not None:
            summary_text_rows.append(("Subtotal", _ngn(subtotal)))
        summary_text_rows.append((f"Delivery{delivery_dest}", _ngn(delivery_fee) if delivery_fee else "—"))
        if discount:
            summary_text_rows.append(("Discount", f"-{_ngn(discount)}"))
        summary_text_rows.append(("Total", _ngn(total)))
        summary_text_rows.append(("Order Number", order_ref))
        if order_date:
            summary_text_rows.append(("Order Date", order_date))
        if order_time:
            summary_text_rows.append(("Order Time", order_time))
        for item in item_list:
            summary_text_rows.append((str(item.get("name") or "Item"),
                                      _ngn(item.get("price")) if item.get("price") is not None else ""))
        text_body = "\n".join(f"{k}: {v}" for k, v in summary_text_rows)
        if not summary_text_rows:
            text_body = items_summary
        text = _base_text(
            from_name=self.from_name, title="Your Order is on the Way",
            greeting=f"Hi {user_name},",
            body=text_body,
        )
        return html, text

    def render_payment_confirmed_email(self, user_name: str, title: str, reference: str,
                                        amount_paid: str, total_paid: Optional[str] = None,
                                        remaining: Optional[str] = None,
                                        balance_label: str = "Remaining Balance",
                                        next_due: Optional[str] = None,
                                        note: Optional[str] = None) -> tuple[str, str]:
        rows = [("Amount Paid", amount_paid)]
        if reference:
            rows.append(("Reference", reference))
        if total_paid:
            rows.append(("Total Paid", total_paid))
        if remaining:
            rows.append((balance_label, remaining))
        if next_due:
            rows.append(("Next Payment Due", next_due))

        body = (
            f'<p style="color:#374151;font-size:15px;line-height:1.6;margin:0 0 20px">'
            f'{escape(note) if note else "Your payment has been confirmed. Thank you!"}</p>'
            + _details_card(rows, "#27ae60")
            + _info_box("Your payment was received successfully.", "#27ae60")
        )
        html = _base_html(
            from_name=self.from_name, icon="💰",
            header_bg="linear-gradient(135deg,#1e8449,#27ae60)",
            header_fg="#fff",
            header_title=title or "Payment Confirmed",
            header_subtitle="Payment received",
            greeting=f"Hello {escape(user_name)},",
            body_html=body,
        )
        text = _base_text(
            from_name=self.from_name, title=title or "Payment Confirmed",
            greeting=f"Hello {user_name},",
            body="\n".join(f"{k}: {v}" for k, v in rows),
        )
        return html, text

    def render_payment_refunded_email(self, user_name: str, amount: str, reason: str,
                                       reference: Optional[str] = None) -> tuple[str, str]:
        rows = [("Amount Refunded", amount), ("Reason", reason)]
        if reference:
            rows.append(("Reference", reference))

        body = (
            f'<p style="color:#374151;font-size:15px;line-height:1.6;margin:0 0 20px">'
            f'Your payment has been refunded. Depending on your bank, it may take a few '
            f'business days to reflect.</p>'
            + _details_card(rows, "#3498db")
            + _info_box("Refund processed successfully.", "#3498db")
        )
        html = _base_html(
            from_name=self.from_name, icon="↩️",
            header_bg="linear-gradient(135deg,#1a5276,#3498db)",
            header_fg="#fff",
            header_title="Payment Refunded",
            header_subtitle="Your refund is on the way",
            greeting=f"Hello {escape(user_name)},",
            body_html=body,
        )
        text = _base_text(
            from_name=self.from_name, title="Payment Refunded",
            greeting=f"Hello {user_name},",
            body="\n".join(f"{k}: {v}" for k, v in rows),
        )
        return html, text

    def render_payment_failed_email(self, user_name: str, asset_title: str, reference: str,
                                     amount: str, reason: Optional[str] = None,
                                     next_attempt: Optional[str] = None,
                                     note: Optional[str] = None) -> tuple[str, str]:
        rows = [("Asset", asset_title), ("Amount", amount)]
        if reference:
            rows.append(("Reference", reference))
        if reason:
            rows.append(("Reason", reason))
        if next_attempt:
            rows.append(("Next Attempt", next_attempt))

        body = (
            f'<p style="color:#374151;font-size:15px;line-height:1.6;margin:0 0 20px">'
            f'{escape(note) if note else "We could not process your recurring payment. Please ensure your account is funded."}</p>'
            + _details_card(rows, "#e74c3c")
            + _alert_box("Missing payments may result in your agreement defaulting.", "#e74c3c")
        )
        html = _base_html(
            from_name=self.from_name, icon="❌",
            header_bg="linear-gradient(135deg,#7d1a1a,#e74c3c)",
            header_fg="#fff",
            header_title="Recurring Payment Failed",
            header_subtitle="Action may be required",
            greeting=f"Hello {escape(user_name)},",
            body_html=body,
        )
        text = _base_text(
            from_name=self.from_name, title="Recurring Payment Failed",
            greeting=f"Hello {user_name},",
            body="\n".join(f"{k}: {v}" for k, v in rows),
        )
        return html, text

    def render_installment_defaulted_email(self, user_name: str, asset_title: str, reference: str,
                                            overdue_amount: str, due_date: str, grace_days,
                                            note: Optional[str] = None) -> tuple[str, str]:
        rows = [
            ("Asset", asset_title),
            ("Overdue Amount", overdue_amount),
            ("Due Date", due_date),
            ("Grace Period", f"{grace_days} day{'s' if str(grace_days) != '1' else ''}"),
        ]
        if reference:
            rows.append(("Reference", reference))

        body = (
            f'<p style="color:#374151;font-size:15px;line-height:1.6;margin:0 0 20px">'
            f'Your agreement has been defaulted because the payment above was not received '
            f'within the grace period.</p>'
            + _details_card(rows, "#e74c3c")
            + _alert_box(note or "Please contact support to discuss reinstating your agreement.", "#e74c3c")
        )
        html = _base_html(
            from_name=self.from_name, icon="⚠️",
            header_bg="linear-gradient(135deg,#7d1a1a,#e74c3c)",
            header_fg="#fff",
            header_title="Agreement Defaulted",
            header_subtitle="Missed payment past grace period",
            greeting=f"Hello {escape(user_name)},",
            body_html=body,
        )
        text = _base_text(
            from_name=self.from_name, title="Agreement Defaulted",
            greeting=f"Hello {user_name},",
            body="\n".join(f"{k}: {v}" for k, v in rows),
        )
        return html, text

    def render_agreement_completed_email(self, user_name: str, asset_title: str, reference: str,
                                          total_paid: str, completed_date: str,
                                          asset_noun: str = "Asset") -> tuple[str, str]:
        rows = [
            ("Asset", asset_title),
            ("Amount Paid", total_paid),
        ]
        if reference:
            rows.append(("Reference", reference))
        if completed_date:
            rows.append(("Completed On", completed_date))

        body = (
            f'<p style="color:#374151;font-size:15px;line-height:1.6;margin:0 0 20px">'
            f'Congratulations! Your agreement has been fully paid and you are now the full '
            f'owner of this {escape(asset_noun.lower())}.</p>'
            + _details_card(rows, "#27ae60")
            + _info_box("Thank you for choosing " + self.from_name + "!", "#27ae60")
        )
        html = _base_html(
            from_name=self.from_name, icon="🎉",
            header_bg="linear-gradient(135deg,#1e8449,#27ae60)",
            header_fg="#fff",
            header_title="You Own It!",
            header_subtitle=f"Your {asset_noun.lower()} is fully paid",
            greeting=f"Hello {escape(user_name)},",
            body_html=body,
        )
        text = _base_text(
            from_name=self.from_name, title="Agreement Completed",
            greeting=f"Hello {user_name},",
            body=("\n".join(f"{k}: {v}" for k, v in rows)
                  + f"\n\nYou are now the full owner of this {asset_noun.lower()}."),
        )
        return html, text

    def render_inspection_rejected_email(self, user_name: str, asset_title: str,
                                          inspection_date: Optional[str] = None,
                                          reason: Optional[str] = None,
                                          note: Optional[str] = None) -> tuple[str, str]:
        rows = [("Asset", asset_title)]
        if inspection_date:
            rows.append(("Inspection Date", inspection_date))
        if reason:
            rows.append(("Reason", reason))

        body = (
            f'<p style="color:#374151;font-size:15px;line-height:1.6;margin:0 0 20px">'
            f'Your inspection request could not proceed. Schedule a new inspection to continue.</p>'
            + _details_card(rows, "#e74c3c")
            + _alert_box(note or "You can schedule another inspection from the asset page.", "#e74c3c")
        )
        html = _base_html(
            from_name=self.from_name, icon="🚫",
            header_bg="linear-gradient(135deg,#7d1a1a,#e74c3c)",
            header_fg="#fff",
            header_title="Inspection Rejected",
            header_subtitle="Your inspection request was declined",
            greeting=f"Hello {escape(user_name)},",
            body_html=body,
        )
        text = _base_text(
            from_name=self.from_name, title="Inspection Rejected",
            greeting=f"Hello {user_name},",
            body="\n".join(f"{k}: {v}" for k, v in rows),
        )
        return html, text

    def render_order_status_email(self, user_name: str, order_id: str, status_label: str,
                                   total: Optional[str] = None, reason: Optional[str] = None,
                                   note: Optional[str] = None) -> tuple[str, str]:
        rows = [
            ("Order ID", f"#{order_id[:8].upper()}" if order_id and order_id != "N/A" else "N/A"),
            ("Status", status_label),
        ]
        if total:
            rows.append(("Total", total))
        if reason:
            rows.append(("Reason", reason))

        body = (
            f'<p style="color:#374151;font-size:15px;line-height:1.6;margin:0 0 20px">'
            f'{escape(note) if note else f"Your order status is now {escape(status_label)}."}</p>'
            + _details_card(rows, "#f39c12")
        )
        html = _base_html(
            from_name=self.from_name, icon="⚙️",
            header_bg="linear-gradient(135deg,#7d3c00,#f39c12)",
            header_fg="#fff",
            header_title=f"Order {status_label}",
            header_subtitle="Order status update",
            greeting=f"Hello {escape(user_name)},",
            body_html=body,
        )
        text = _base_text(
            from_name=self.from_name, title=f"Order {status_label}",
            greeting=f"Hello {user_name},",
            body="\n".join(f"{k}: {v}" for k, v in rows),
        )
        return html, text

    def render_notification_email(self, notification_type: str, title: str,
                                   message: str, user_name: str,
                                   data: Optional[dict] = None) -> tuple[str, str]:
        """
        Smart dispatcher: routes to a specific template when possible, falling
        back to a generic one. A failure inside a specific template never drops
        the email - it degrades to the generic template instead.
        """
        d = data or {}
        try:
            rendered = self._render_specific_notification_email(
                notification_type, title, message, user_name, d
            )
            if rendered is not None:
                return rendered
        except Exception:
            logger.exception(
                f"Specific email template failed for type '{notification_type}'; "
                f"falling back to generic template."
            )

        # --- Generic fallback ---
        return self._render_generic_notification_email(
            notification_type, title, message, user_name, d
        )

    def _render_specific_notification_email(self, notification_type: str, title: str,
                                            message: str, user_name: str,
                                            d: dict) -> Optional[tuple[str, str]]:
        """Return a specific template render, or None to use the generic fallback."""
        if notification_type == "inspection_confirmed":
            return self.render_inspection_confirmed_email(
                user_name=user_name,
                asset_title=d.get("asset_title") or "Asset",
                inspection_date=d.get("inspection_date") or "Scheduled",
                location=d.get("location"),
                seller_name=d.get("seller_name") or "Seller",
                seller_contact=d.get("seller_contact"),
            )

        if notification_type == "agreement_activated":
            return self.render_agreement_activated_email(
                user_name=user_name,
                asset_title=d.get("asset_title") or "Asset",
                total_price=d.get("total_price"),
                amount_paid=d.get("amount_paid"),
                remaining=d.get("remaining_balance"),
                monthly=d.get("monthly_installment"),
                next_due=d.get("next_due_date"),
                reference=d.get("reference") or _ref(d.get("agreement_id")),
            )

        if notification_type == "agreement_completed":
            return self.render_agreement_completed_email(
                user_name=user_name,
                asset_title=d.get("asset_title") or "Asset",
                reference=d.get("reference") or _ref(d.get("agreement_id")),
                total_paid=_ngn(d.get("total_paid") or d.get("total_amount") or d.get("total_price")),
                completed_date=d.get("completed_date") or d.get("completed_on") or "",
                asset_noun=d.get("asset_noun") or "Asset",
            )

        if notification_type in ("agreement_approved", "agreement_update") and d.get("asset_title"):
            return self.render_agreement_approved_email(
                user_name=user_name,
                asset_title=d.get("asset_title"),
                total_price=d.get("total_price") or "",
                remaining=d.get("remaining_balance") or "",
                next_due=d.get("next_due_date"),
                monthly=d.get("monthly_installment"),
                reference=d.get("reference") or _ref(d.get("agreement_id")),
            )

        if notification_type == "agreement_created" and d.get("asset_title"):
            return self.render_agreement_created_email(
                seller_name=user_name,
                buyer_name=d.get("buyer_name") or "Buyer",
                asset_title=d.get("asset_title"),
                total_price=d.get("total_price") or "",
                deposit=d.get("deposit") or "",
                plan_type=d.get("plan_type") or "structured",
                monthly=d.get("monthly_installment"),
                duration=d.get("duration_months"),
            )

        if notification_type in ("installment_due", "payment_reminder") and d.get("amount_due"):
            return self.render_installment_reminder_email(
                user_name=user_name,
                asset_title=d.get("asset_title") or "Asset",
                amount_due=_ngn(d.get("amount_due")),
                due_date=d.get("due_date") or "",
                days_left=int(d.get("days_left", 3)),
                remaining_balance=_ngn(d.get("remaining_balance")) if d.get("remaining_balance") is not None else None,
            )

        if notification_type in ("payment_successful", "installment_paid") and (
            d.get("amount") is not None or d.get("amount_paid") is not None
        ):
            context = (d.get("context") or "").lower()
            amount_this = d.get("amount") if d.get("amount") is not None else d.get("amount_paid")
            total_paid_val = d.get("amount_paid")
            amount_paid_str = _ngn(amount_this)
            total_paid_str = _ngn(total_paid_val) if total_paid_val is not None else None
            if total_paid_str and total_paid_str == amount_paid_str:
                total_paid_str = None
            return self.render_payment_confirmed_email(
                user_name=user_name,
                title=title or "Payment Confirmed",
                reference=d.get("reference") or _ref(d.get("order_id")) or _ref(d.get("agreement_id")),
                amount_paid=amount_paid_str,
                total_paid=total_paid_str,
                remaining=_ngn(d.get("remaining_balance")) if d.get("remaining_balance") is not None else None,
                balance_label="Remaining Balance",
                next_due=d.get("next_due_date"),
                note=d.get("note"),
            )

        if notification_type == "payment_refunded":
            return self.render_payment_refunded_email(
                user_name=user_name,
                amount=_ngn(d.get("amount")),
                reason=d.get("reason") or d.get("note") or "Refund processed",
                reference=d.get("reference") or _ref(d.get("order_id")),
            )

        if notification_type == "payment_failed":
            return self.render_payment_failed_email(
                user_name=user_name,
                asset_title=d.get("asset_title") or "Asset",
                reference=d.get("reference") or _ref(d.get("agreement_id")) or _ref(d.get("order_id")),
                amount=_ngn(d.get("amount") if d.get("amount") is not None else d.get("amount_due")),
                reason=d.get("reason"),
                next_attempt=d.get("next_attempt"),
                note=d.get("note") or message,
            )

        if notification_type == "installment_defaulted":
            return self.render_installment_defaulted_email(
                user_name=user_name,
                asset_title=d.get("asset_title") or "Asset",
                reference=d.get("reference") or _ref(d.get("agreement_id")),
                overdue_amount=_ngn(d.get("overdue_amount") or d.get("amount") or d.get("monthly_installment")),
                due_date=d.get("due_date") or "—",
                grace_days=d.get("grace_days", 0),
                note=d.get("note"),
            )

        if notification_type == "inspection_rejected":
            return self.render_inspection_rejected_email(
                user_name=user_name,
                asset_title=d.get("asset_title") or "Asset",
                inspection_date=d.get("inspection_date"),
                reason=d.get("reason"),
                note=d.get("note"),
            )

        if notification_type == "order_confirmed":
            return self.render_order_confirmed_email(
                user_name=user_name,
                order_id=d.get("order_id") or "N/A",
                items_summary=d.get("items_summary") or "Your items",
                total=d.get("total_amount") if d.get("total_amount") is not None else d.get("amount"),
                delivery_type=d.get("delivery_type") or "delivery",
                delivery_fee=d.get("delivery_fee"),
                estimated_delivery=d.get("estimated_delivery"),
                subtotal=d.get("subtotal"),
                discount=d.get("discount"),
                delivery_city=d.get("delivery_city"),
                order_date=d.get("order_date"),
                order_time=d.get("order_time"),
                items=d.get("items"),
            )

        if notification_type == "order_processing":
            return self.render_order_status_email(
                user_name=user_name,
                order_id=d.get("order_id") or "N/A",
                status_label="Processing",
                total=_ngn(d.get("total_amount")) if d.get("total_amount") is not None else None,
                note=d.get("notes"),
            )

        if notification_type == "order_cancelled":
            return self.render_order_status_email(
                user_name=user_name,
                order_id=d.get("order_id") or "N/A",
                status_label="Cancelled",
                total=_ngn(d.get("total_amount")) if d.get("total_amount") is not None else None,
                reason=d.get("reason") or d.get("notes"),
            )

        if notification_type == "order_shipped":
            return self.render_order_shipped_email(
                user_name=user_name,
                order_id=d.get("order_id") or "N/A",
                items_summary=d.get("items_summary") or "Your items",
                total=_ngn(d.get("amount") if d.get("amount") is not None else d.get("total_amount")),
                tracking_note=d.get("tracking_note"),
            )

        if notification_type == "order_delivered":
            return self.render_order_delivered_email(
                user_name=user_name,
                order_id=d.get("order_id") or "N/A",
                items_summary=d.get("items_summary") or "Your items",
                total=_ngn(d.get("amount") if d.get("amount") is not None else d.get("total_amount")),
            )

        if d.get("dispute_id"):
            dispute_event = d.get("dispute_event")
            if dispute_event == "resolved" or d.get("resolved"):
                return self.render_dispute_resolved_email(
                    user_name=user_name,
                    dispute_title=title,
                    resolution=d.get("resolution") or "Resolved",
                    notes=d.get("resolution_notes"),
                )
            if dispute_event == "opened":
                return self.render_dispute_opened_email(
                    user_name=user_name,
                    dispute_title=title,
                    reference=d.get("dispute_id", "")[:8].upper(),
                    order_or_agreement_id=d.get("order_id") or d.get("agreement_id"),
                )
            # Other dispute updates (e.g. status changes) use the generic template.

        # No specific template matched — use the generic fallback.
        return None

    def _render_generic_notification_email(self, notification_type: str, title: str,
                                            message: str, user_name: str,
                                            data: dict) -> tuple[str, str]:
        color_map = {
            "payment_successful": ("#27ae60", "💰"),
            "payment_failed": ("#e74c3c", "❌"),
            "order_confirmed": ("#FFD700", "📋"),
            "order_processing": ("#f39c12", "⚙️"),
            "order_shipped": ("#3498db", "🚚"),
            "order_delivered": ("#27ae60", "📦"),
            "order_cancelled": ("#e74c3c", "🚫"),
            "car_approved": ("#27ae60", "🚗"),
            "car_rejected": ("#e74c3c", "🚗"),
            "property_acquired": ("#8e44ad", "🏠"),
            "system_announcement": ("#3498db", "📢"),
            "promotional_offer": ("#e74c3c", "🎁"),
            "payment_refunded": ("#3498db", "↩️"),
            "agreement_activated": ("#27ae60", "✅"),
            "agreement_completed": ("#27ae60", "🎉"),
            "installment_defaulted": ("#e74c3c", "⚠️"),
            "inspection_rejected": ("#e74c3c", "🚫"),
        }
        accent, icon = color_map.get(notification_type, ("#FFD700", "🔔"))

        # Show user-facing key/value pairs from data, dropping internal-only keys
        # and formatting currency values.
        detail_rows = []
        for k, v in data.items():
            if not v or k in _INTERNAL_DATA_KEYS:
                continue
            text = _ngn(v) if any(h in k.lower() for h in _MONEY_KEY_HINTS) else str(v)
            detail_rows.append((k.replace("_", " ").title(), text))
        details_html = _details_card(detail_rows, accent) if detail_rows else ""

        body = (
            f'<p style="color:#374151;font-size:15px;line-height:1.6;margin:0 0 20px">'
            f'{escape(message)}</p>'
            + details_html
        )
        html = _base_html(
            from_name=self.from_name, icon=icon,
            header_bg=f"linear-gradient(135deg,#111,{accent})",
            header_fg="#fff",
            header_title=title,
            header_subtitle="Notification from " + self.from_name,
            greeting=f"Hello {escape(user_name)},",
            body_html=body,
        )
        detail_text = "\n".join(f"{k}: {v}" for k, v in detail_rows)
        text = _base_text(
            from_name=self.from_name, title=title,
            greeting=f"Hello {user_name},",
            body=message + (f"\n\n{detail_text}" if detail_text else ""),
        )
        return html, text


email_service = EmailService()
