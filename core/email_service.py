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
# Shared HTML building blocks
# ---------------------------------------------------------------------------

def _detail_row(label: str, value: str, value_color: str = "#e0e0e0") -> str:
    safe_val = escape(str(value)) if value else "—"
    return (
        f'<tr>'
        f'<td style="padding:8px 16px 8px 0;color:#888;font-size:13px;'
        f'white-space:nowrap;vertical-align:top">{escape(label)}</td>'
        f'<td style="padding:8px 0;color:{value_color};font-size:14px;'
        f'font-weight:600">{safe_val}</td>'
        f'</tr>'
    )


def _details_card(rows: list[tuple[str, str]], accent: str = "#FFD700") -> str:
    rows_html = "".join(_detail_row(k, v) for k, v in rows if v)
    return (
        f'<div style="background:#1a1a1a;border-left:4px solid {accent};'
        f'border-radius:8px;padding:20px 24px;margin:24px 0">'
        f'<table style="width:100%;border-collapse:collapse">'
        f'{rows_html}'
        f'</table></div>'
    )


def _alert_box(text: str, color: str = "#ff6b6b") -> str:
    return (
        f'<div style="background:{color}1a;border-left:4px solid {color};'
        f'border-radius:8px;padding:16px 20px;margin:20px 0">'
        f'<p style="color:{color};margin:0;font-size:14px;line-height:1.5">'
        f'{escape(text)}</p></div>'
    )


def _info_box(text: str, color: str = "#FFD700") -> str:
    return (
        f'<div style="background:{color}15;border:1px solid {color}40;'
        f'border-radius:8px;padding:16px 20px;margin:20px 0;text-align:center">'
        f'<p style="color:{color};margin:0;font-size:15px;font-weight:600">'
        f'{escape(text)}</p></div>'
    )


def _base_html(
    *,
    from_name: str,
    icon: str,
    header_bg: str,
    header_fg: str,
    header_title: str,
    header_subtitle: str,
    greeting: str,
    body_html: str,
    footer_note: str = "",
) -> str:
    footer_note_html = (
        f'<p style="color:#666;font-size:12px;margin:8px 0">'
        f'{escape(footer_note)}</p>'
        if footer_note else ""
    )
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width,initial-scale=1.0">
  <title>{escape(header_title)}</title>
</head>
<body style="margin:0;padding:0;background:#111;font-family:'Segoe UI',Arial,sans-serif">
  <table width="100%" cellpadding="0" cellspacing="0" style="background:#111;padding:32px 0">
    <tr><td align="center">
      <table width="600" cellpadding="0" cellspacing="0"
             style="max-width:600px;width:100%;background:#0d0d0d;border-radius:16px;
                    overflow:hidden;box-shadow:0 8px 40px rgba(0,0,0,0.6)">

        <!-- HEADER -->
        <tr>
          <td style="background:{header_bg};padding:36px 32px;text-align:center">
            <div style="font-size:42px;margin-bottom:12px">{icon}</div>
            <div style="font-size:24px;font-weight:800;color:{header_fg};
                        letter-spacing:-.5px;margin-bottom:4px">{escape(from_name)}</div>
            <div style="font-size:16px;font-weight:700;color:{header_fg};opacity:.9">
              {escape(header_title)}</div>
            <div style="font-size:13px;color:{header_fg};opacity:.7;margin-top:4px">
              {escape(header_subtitle)}</div>
          </td>
        </tr>

        <!-- BODY -->
        <tr>
          <td style="padding:36px 40px">
            <p style="color:#e0e0e0;font-size:16px;margin:0 0 24px;font-weight:600">
              {escape(greeting)}</p>
            {body_html}
          </td>
        </tr>

        <!-- FOOTER -->
        <tr>
          <td style="background:#080808;padding:24px 40px;text-align:center;
                     border-top:1px solid #222">
            <p style="color:#555;font-size:13px;margin:0 0 4px">
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
            f'<p style="color:#e0e0e0;font-size:15px;line-height:1.6;margin:0 0 20px">'
            f'Thank you for joining <strong>{escape(self.from_name)}</strong>! '
            f'Enter the code below to verify your email address and activate your account.</p>'
            f'<div style="background:#1a1a1a;border:2px solid #FFD700;border-radius:12px;'
            f'padding:32px;text-align:center;margin:24px 0;'
            f'box-shadow:0 0 30px rgba(255,215,0,.15)">'
            f'<p style="color:#888;font-size:12px;text-transform:uppercase;'
            f'letter-spacing:2px;margin:0 0 12px">Verification Code</p>'
            f'<div style="font-size:40px;font-weight:900;letter-spacing:12px;color:#FFD700;'
            f'font-family:monospace">{escape(verification_code)}</div>'
            f'<p style="color:#666;font-size:13px;margin:12px 0 0">Expires in {expire} minutes</p>'
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
            f'<p style="color:#e0e0e0;font-size:15px;line-height:1.6;margin:0 0 20px">'
            f'We received a request to reset your password. '
            f'Use the code below to create a new password.</p>'
            f'<div style="background:#1a0a0a;border:2px solid #ff6b6b;border-radius:12px;'
            f'padding:32px;text-align:center;margin:24px 0;'
            f'box-shadow:0 0 30px rgba(255,107,107,.15)">'
            f'<p style="color:#888;font-size:12px;text-transform:uppercase;'
            f'letter-spacing:2px;margin:0 0 12px">Reset Code</p>'
            f'<div style="font-size:40px;font-weight:900;letter-spacing:12px;color:#ff6b6b;'
            f'font-family:monospace">{escape(reset_code)}</div>'
            f'<p style="color:#666;font-size:13px;margin:12px 0 0">Expires in {expire} minutes</p>'
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
            f'<p style="color:#e0e0e0;font-size:15px;line-height:1.6;margin:0 0 16px">'
            f'Welcome to <strong>{escape(self.from_name)}</strong>! '
            f'Your email has been verified and your account is ready to use.</p>'
            + _info_box("🎉 Your account is now active!")
            + f'<p style="color:#aaa;font-size:14px;line-height:1.6;margin:16px 0 0">'
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
            f'<p style="color:#e0e0e0;font-size:15px;line-height:1.6;margin:0 0 20px">'
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

    def render_kyc_approved_email(self, business_name: str, approval_date: str) -> tuple[str, str]:
        body = (
            f'<p style="color:#e0e0e0;font-size:15px;line-height:1.6;margin:0 0 20px">'
            f'Great news — your KYC (Know Your Customer) verification has been approved. '
            f'You can now start listing and selling on <strong>{escape(self.from_name)}</strong>.</p>'
            + _details_card([
                ("Business Name", business_name),
                ("Approval Date", approval_date),
                ("Status", "✅ Approved"),
            ], "#27ae60")
            + _info_box("You're now a verified seller. Start listing your assets today!", "#27ae60")
        )
        html = _base_html(
            from_name=self.from_name, icon="✅",
            header_bg="linear-gradient(135deg,#1e8449,#27ae60)",
            header_fg="#fff",
            header_title="KYC Approved",
            header_subtitle="Your seller account is verified",
            greeting=f"Hello {escape(business_name)},",
            body_html=body,
        )
        text = _base_text(
            from_name=self.from_name, title="KYC Approved",
            greeting=f"Hello {business_name},",
            body=(f"Your KYC verification has been approved on {approval_date}.\n\n"
                  f"You can now list and sell assets on {self.from_name}."),
        )
        return html, text

    def render_kyc_rejected_email(self, business_name: str,
                                   reason: Optional[str] = None) -> tuple[str, str]:
        reason_block = (
            _details_card([("Reason", reason)], "#e74c3c")
            if reason else ""
        )
        body = (
            f'<p style="color:#e0e0e0;font-size:15px;line-height:1.6;margin:0 0 20px">'
            f'Unfortunately, your KYC verification was not approved at this time. '
            f'Please review the information below and resubmit your documents.</p>'
            + reason_block
            + _alert_box(
                "Please ensure all documents are valid, legible, and match your business registration. "
                "Resubmit through your seller dashboard.", "#e74c3c"
            )
        )
        html = _base_html(
            from_name=self.from_name, icon="⚠️",
            header_bg="linear-gradient(135deg,#922b21,#e74c3c)",
            header_fg="#fff",
            header_title="KYC Verification Required",
            header_subtitle="Action needed to activate your seller account",
            greeting=f"Hello {escape(business_name)},",
            body_html=body,
        )
        text = _base_text(
            from_name=self.from_name, title="KYC Not Approved",
            greeting=f"Hello {business_name},",
            body=(f"Your KYC verification was not approved.\n"
                  + (f"Reason: {reason}\n" if reason else "")
                  + "\nPlease resubmit your documents through your seller dashboard."),
        )
        return html, text

    def render_payout_requested_email(self, business_name: str, amount: str,
                                       bank_name: str, account_number: str) -> tuple[str, str]:
        body = (
            f'<p style="color:#e0e0e0;font-size:15px;line-height:1.6;margin:0 0 20px">'
            f'Your payout request has been received and is pending processing by our team.</p>'
            + _details_card([
                ("Amount Requested", amount),
                ("Bank", bank_name),
                ("Account Number", account_number[-4:].rjust(len(account_number), "*")),
                ("Status", "⏳ Pending"),
            ], "#FFD700")
            + _info_box("Payouts are typically processed within 1–2 business days.")
        )
        html = _base_html(
            from_name=self.from_name, icon="💸",
            header_bg="linear-gradient(135deg,#7d6608,#d4ac0d)",
            header_fg="#fff",
            header_title="Payout Request Received",
            header_subtitle="We'll notify you once it's processed",
            greeting=f"Hello {escape(business_name)},",
            body_html=body,
        )
        text = _base_text(
            from_name=self.from_name, title="Payout Request Received",
            greeting=f"Hello {business_name},",
            body=(f"Your payout request of {amount} to {bank_name} has been received.\n"
                  f"It will be processed within 1–2 business days."),
        )
        return html, text

    def render_payout_completed_email(self, business_name: str, amount: str,
                                       bank_name: str, reference: str) -> tuple[str, str]:
        body = (
            f'<p style="color:#e0e0e0;font-size:15px;line-height:1.6;margin:0 0 20px">'
            f'Great news — your payout has been successfully processed and sent to your bank account.</p>'
            + _details_card([
                ("Amount Transferred", amount),
                ("Bank", bank_name),
                ("Reference", reference),
                ("Status", "✅ Completed"),
            ], "#27ae60")
            + _info_box("Your funds should appear in your account within minutes.", "#27ae60")
        )
        html = _base_html(
            from_name=self.from_name, icon="🏦",
            header_bg="linear-gradient(135deg,#1e8449,#27ae60)",
            header_fg="#fff",
            header_title="Payout Successful",
            header_subtitle="Your funds are on their way",
            greeting=f"Hello {escape(business_name)},",
            body_html=body,
        )
        text = _base_text(
            from_name=self.from_name, title="Payout Successful",
            greeting=f"Hello {business_name},",
            body=(f"Your payout of {amount} has been sent to {bank_name}.\n"
                  f"Reference: {reference}"),
        )
        return html, text

    def render_payout_failed_email(self, business_name: str, amount: str,
                                    reason: str) -> tuple[str, str]:
        body = (
            f'<p style="color:#e0e0e0;font-size:15px;line-height:1.6;margin:0 0 20px">'
            f'Unfortunately, your payout could not be processed. '
            f'The amount has been returned to your available balance.</p>'
            + _details_card([
                ("Amount", amount),
                ("Status", "❌ Failed"),
                ("Reason", reason),
            ], "#e74c3c")
            + _alert_box(
                "Please check your bank account details in your seller dashboard and try again.",
                "#e74c3c"
            )
        )
        html = _base_html(
            from_name=self.from_name, icon="❌",
            header_bg="linear-gradient(135deg,#922b21,#e74c3c)",
            header_fg="#fff",
            header_title="Payout Failed",
            header_subtitle="Your balance has been restored",
            greeting=f"Hello {escape(business_name)},",
            body_html=body,
        )
        text = _base_text(
            from_name=self.from_name, title="Payout Failed",
            greeting=f"Hello {business_name},",
            body=(f"Your payout of {amount} failed.\nReason: {reason}\n\n"
                  f"The amount has been returned to your available balance."),
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
            f'<p style="color:#e0e0e0;font-size:15px;line-height:1.6;margin:0 0 20px">'
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
            f'<p style="color:#e0e0e0;font-size:15px;line-height:1.6;margin:0 0 20px">'
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
                                         monthly: Optional[str] = None) -> tuple[str, str]:
        rows = [
            ("Asset", asset_title),
            ("Total Price", total_price),
            ("Remaining Balance", remaining),
        ]
        if monthly:
            rows.append(("Monthly Installment", monthly))
        if next_due:
            rows.append(("Next Payment Due", next_due))

        body = (
            f'<p style="color:#e0e0e0;font-size:15px;line-height:1.6;margin:0 0 20px">'
            f'Your purchase agreement for <strong>{escape(asset_title)}</strong> is now active. '
            f'Your deposit has been confirmed and your installment plan has started.</p>'
            + _details_card(rows, "#27ae60")
            + _info_box("Keep up with your payments to complete the purchase.", "#27ae60")
        )
        html = _base_html(
            from_name=self.from_name, icon="🤝",
            header_bg="linear-gradient(135deg,#1e8449,#27ae60)",
            header_fg="#fff",
            header_title="Agreement Approved",
            header_subtitle="Your installment plan is now active",
            greeting=f"Hello {escape(user_name)},",
            body_html=body,
        )
        text = _base_text(
            from_name=self.from_name, title="Agreement Approved",
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
            f'<p style="color:#e0e0e0;font-size:15px;line-height:1.6;margin:0 0 20px">'
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
            f'<p style="color:#e0e0e0;font-size:15px;line-height:1.6;margin:0 0 20px">'
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
            f'<p style="color:#e0e0e0;font-size:15px;line-height:1.6;margin:0 0 20px">'
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
            f'<p style="color:#e0e0e0;font-size:15px;line-height:1.6;margin:0 0 20px">'
            f'Your order has been dispatched and is on its way to you!</p>'
            + _details_card(rows, "#3498db")
            + _info_box(
                tracking_note or "You will pay the delivery fee directly to the courier.",
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
            f'<p style="color:#e0e0e0;font-size:15px;line-height:1.6;margin:0 0 20px">'
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

    def render_notification_email(self, notification_type: str, title: str,
                                   message: str, user_name: str,
                                   data: Optional[dict] = None) -> tuple[str, str]:
        """
        Smart dispatcher: routes to a specific template when possible,
        falls back to a generic one.
        """
        d = data or {}

        # --- Specific dispatches ---
        if notification_type == "inspection_confirmed":
            return self.render_inspection_confirmed_email(
                user_name=user_name,
                asset_title=d.get("asset_title") or "Asset",
                inspection_date=d.get("inspection_date") or "Scheduled",
                location=d.get("location"),
                seller_name=d.get("seller_name") or "Seller",
                seller_contact=d.get("seller_contact"),
            )

        if notification_type in ("agreement_approved", "agreement_update") and d.get("asset_title"):
            return self.render_agreement_approved_email(
                user_name=user_name,
                asset_title=d.get("asset_title"),
                total_price=d.get("total_price") or "",
                remaining=d.get("remaining_balance") or "",
                next_due=d.get("next_due_date"),
                monthly=d.get("monthly_installment"),
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

        if notification_type == "payment_successful" and d.get("payout_id"):
            return self.render_payout_completed_email(
                business_name=user_name,
                amount=f"₦{float(d.get('amount', 0)):,.2f}",
                bank_name=d.get("bank_name") or "",
                reference=d.get("transfer_reference") or d.get("payout_id", "")[:12].upper(),
            )

        if notification_type == "payment_failed" and d.get("payout_id"):
            return self.render_payout_failed_email(
                business_name=user_name,
                amount=f"₦{float(d.get('amount', 0)):,.2f}",
                reason=d.get("failure_reason") or "Transfer could not be processed",
            )

        if notification_type == "account_verified" and d.get("kyc_status") == "approved":
            return self.render_kyc_approved_email(
                business_name=user_name,
                approval_date=d.get("approval_date") or "Today",
            )

        if notification_type == "account_verified" and d.get("kyc_status") == "rejected":
            return self.render_kyc_rejected_email(
                business_name=user_name,
                reason=d.get("rejection_reason"),
            )

        if notification_type in ("installment_due", "payment_reminder") and d.get("amount_due"):
            return self.render_installment_reminder_email(
                user_name=user_name,
                asset_title=d.get("asset_title") or "Asset",
                amount_due=d.get("amount_due") or "",
                due_date=d.get("due_date") or "",
                days_left=int(d.get("days_left", 3)),
                remaining_balance=d.get("remaining_balance"),
            )

        if notification_type == "order_shipped":
            return self.render_order_shipped_email(
                user_name=user_name,
                order_id=d.get("order_id") or "N/A",
                items_summary=d.get("items_summary") or "Your items",
                total=d.get("amount") and f"₦{float(d['amount']):,.2f}" or "",
            )

        if notification_type == "order_delivered":
            return self.render_order_delivered_email(
                user_name=user_name,
                order_id=d.get("order_id") or "N/A",
                items_summary=d.get("items_summary") or "Your items",
                total=d.get("amount") and f"₦{float(d['amount']):,.2f}" or "",
            )

        if d.get("dispute_id"):
            if d.get("resolved"):
                return self.render_dispute_resolved_email(
                    user_name=user_name,
                    dispute_title=title,
                    resolution=d.get("resolution") or "Resolved",
                    notes=d.get("resolution_notes"),
                )
            return self.render_dispute_opened_email(
                user_name=user_name,
                dispute_title=title,
                reference=d.get("dispute_id", "")[:8].upper(),
                order_or_agreement_id=d.get("order_id") or d.get("agreement_id"),
            )

        # --- Generic fallback ---
        return self._render_generic_notification_email(
            notification_type, title, message, user_name, d
        )

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
        }
        accent, icon = color_map.get(notification_type, ("#FFD700", "🔔"))

        # Show key/value pairs from data when available
        detail_rows = [
            (k.replace("_", " ").title(), str(v))
            for k, v in data.items()
            if v and k not in ("user_id", "seller_id")
        ]
        details_html = _details_card(detail_rows, accent) if detail_rows else ""

        body = (
            f'<p style="color:#e0e0e0;font-size:15px;line-height:1.6;margin:0 0 20px">'
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
        text = _base_text(
            from_name=self.from_name, title=title,
            greeting=f"Hello {user_name},",
            body=message,
        )
        return html, text


email_service = EmailService()
