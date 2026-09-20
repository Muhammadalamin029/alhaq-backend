"""Render-only tests for the email templates.

No SMTP is touched: every test renders a template (or dispatches through
``render_notification_email``) and asserts the output is non-empty and carries
the key fields for that event.

Run directly (pytest is not a dependency of this project):

    ./.venv/bin/python tests/test_email_render.py

The module is also pytest-compatible (plain ``test_*`` functions).
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.email_service import email_service, _ngn, _ref  # noqa: E402


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _assert_rendered(result, *needles, label=""):
    assert isinstance(result, tuple) and len(result) == 2, f"{label}: not an (html, text) tuple"
    html, text = result
    assert isinstance(html, str) and html.strip(), f"{label}: empty html"
    assert isinstance(text, str) and text.strip(), f"{label}: empty text"
    for needle in needles:
        assert needle in html, f"{label}: {needle!r} missing from html"
        assert needle in text, f"{label}: {needle!r} missing from text"
    return html, text


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------

def test_formatting_helpers():
    assert _ngn(1234.5) == "₦1,234.50"
    assert _ngn("5000") == "₦5,000.00"
    assert _ngn("₦1,000.00") == "₦1,000.00"
    assert _ngn(None) == ""
    assert _ref("abcdef123456") == "ABCDEF12"
    assert _ref(None) == ""


# ---------------------------------------------------------------------------
# Direct templates
# ---------------------------------------------------------------------------

def test_verification_email():
    _assert_rendered(
        email_service.render_verification_email("Ada", "123456"),
        "123456", label="verification",
    )


def test_password_reset_email():
    _assert_rendered(
        email_service.render_password_reset_email("Ada", "654321"),
        "654321", label="password_reset",
    )


def test_welcome_email():
    _assert_rendered(
        email_service.render_welcome_email("Ada"), "Ada", label="welcome",
    )


def test_login_email():
    _assert_rendered(
        email_service.render_login_email("Ada", "Jan 1, 2026", "1.2.3.4", "Chrome"),
        "1.2.3.4", "Chrome", label="login",
    )


def test_inspection_confirmed_email():
    _assert_rendered(
        email_service.render_inspection_confirmed_email(
            "Ada", "Toyota Camry", "Jan 1, 2026", "Lagos", "Store", "0800"
        ),
        "Toyota Camry", label="inspection_confirmed",
    )


def test_agreement_created_email():
    _assert_rendered(
        email_service.render_agreement_created_email(
            "Seller", "Ada", "Toyota Camry", "₦10,000,000.00",
            "₦2,000,000.00", "structured", "₦500,000.00", "12",
        ),
        "Toyota Camry", label="agreement_created",
    )


def test_agreement_approved_email_is_deposit_oriented():
    html, text = _assert_rendered(
        email_service.render_agreement_approved_email(
            "Ada", "Toyota Camry", "₦10,000,000.00", "₦8,000,000.00",
            "Feb 1, 2026", "₦500,000.00", "ABCDEF12",
        ),
        "Toyota Camry", "ABCDEF12", "deposit", label="agreement_approved",
    )
    assert "Deposit Required" in html or "Deposit Required" in text


def test_agreement_activated_email():
    _assert_rendered(
        email_service.render_agreement_activated_email(
            "Ada", "Toyota Camry", 10_000_000, 2_000_000, 8_000_000,
            monthly=500_000, next_due="Feb 1, 2026", reference="ABCDEF12",
        ),
        "Toyota Camry", "ABCDEF12", label="agreement_activated",
    )


def test_financing_approved_email():
    _assert_rendered(
        email_service.render_financing_application_approved_email(
            "Ada", "ABCDEF12", "Jan 1, 2026"
        ),
        "ABCDEF12", "Jan 1, 2026", label="financing_approved",
    )


def test_financing_rejected_email():
    _assert_rendered(
        email_service.render_financing_application_rejected_email(
            "Ada", "Low income", "ABCDEF12", "Jan 1, 2026"
        ),
        "Low income", "ABCDEF12", label="financing_rejected",
    )


def test_financing_revoked_email():
    _assert_rendered(
        email_service.render_financing_application_revoked_email(
            "Ada", "Policy change", "ABCDEF12", "Jan 1, 2026"
        ),
        "Policy change", "ABCDEF12", label="financing_revoked",
    )


def test_installment_reminder_email():
    _assert_rendered(
        email_service.render_installment_reminder_email(
            "Ada", "Toyota Camry", "₦500,000.00", "Feb 1, 2026", 3, "₦7,500,000.00"
        ),
        "Toyota Camry", label="installment_reminder",
    )


def test_dispute_opened_email():
    _assert_rendered(
        email_service.render_dispute_opened_email("Ada", "Wrong item", "ABCDEF12"),
        "Wrong item", label="dispute_opened",
    )


def test_dispute_resolved_email():
    _assert_rendered(
        email_service.render_dispute_resolved_email(
            "Ada", "Wrong item", "refund_issued", "Refunded"
        ),
        "Wrong item", label="dispute_resolved",
    )


def test_order_shipped_email():
    _assert_rendered(
        email_service.render_order_shipped_email(
            "Ada", "abcdef123456", "2× Phone", "₦2,000.00"
        ),
        "2× Phone", label="order_shipped",
    )


def test_order_delivered_email():
    _assert_rendered(
        email_service.render_order_delivered_email(
            "Ada", "abcdef123456", "2× Phone", "₦2,000.00"
        ),
        "2× Phone", label="order_delivered",
    )


def test_order_confirmed_email():
    _assert_rendered(
        email_service.render_order_confirmed_email(
            "Ada", "abcdef123456", "2× Phone", "₦2,000.00",
            "delivery", "₦1,000.00", "Feb 1, 2026",
        ),
        "2× Phone", "Feb 1, 2026", label="order_confirmed",
    )


def test_payment_confirmed_email():
    _assert_rendered(
        email_service.render_payment_confirmed_email(
            "Ada", "Order Payment Confirmed", "ABCDEF12", "₦5,000.00",
            total_paid="₦5,000.00", remaining="₦0.00", next_due="Feb 1, 2026",
        ),
        "ABCDEF12", label="payment_confirmed",
    )


def test_payment_refunded_email():
    _assert_rendered(
        email_service.render_payment_refunded_email(
            "Ada", "₦5,000.00", "Duplicate charge", "ABCDEF12"
        ),
        "Duplicate charge", label="payment_refunded",
    )


def test_payment_failed_email():
    _assert_rendered(
        email_service.render_payment_failed_email(
            "Ada", "Toyota Camry", "ABCDEF12", "₦500,000.00",
            reason="Insufficient funds", next_attempt="Feb 1, 2026",
        ),
        "Toyota Camry", "Insufficient funds", label="payment_failed",
    )


def test_installment_defaulted_email():
    _assert_rendered(
        email_service.render_installment_defaulted_email(
            "Ada", "Toyota Camry", "ABCDEF12", "₦500,000.00", "Jan 1, 2026", 3
        ),
        "Toyota Camry", label="installment_defaulted",
    )


def test_agreement_completed_email():
    html, text = _assert_rendered(
        email_service.render_agreement_completed_email(
            "Ada", "Toyota Camry", "ABCDEF12", "₦10,000,000.00",
            "Jan 1, 2026", "Car",
        ),
        "Toyota Camry", label="agreement_completed",
    )
    assert "LEL Store" not in html and "LEL Store" not in text


def test_inspection_rejected_email():
    _assert_rendered(
        email_service.render_inspection_rejected_email(
            "Ada", "Toyota Camry", "Jan 1, 2026", "Declined by seller"
        ),
        "Toyota Camry", label="inspection_rejected",
    )


def test_order_status_email():
    _assert_rendered(
        email_service.render_order_status_email(
            "Ada", "abcdef123456", "Processing", total="₦2,000.00"
        ),
        "Processing", label="order_status",
    )


# ---------------------------------------------------------------------------
# Dispatcher branches
# ---------------------------------------------------------------------------

def test_dispatcher_agreement_activated():
    _assert_rendered(
        email_service.render_notification_email(
            "agreement_activated", "Agreement Activated", "msg", "Ada",
            {
                "asset_title": "Toyota Camry",
                "total_price": 10_000_000,
                "amount_paid": 2_000_000,
                "remaining_balance": 8_000_000,
                "monthly_installment": 500_000,
                "next_due_date": "Feb 1, 2026",
                "reference": "ABCDEF12",
            },
        ),
        "Toyota Camry", "ABCDEF12", label="dispatch:agreement_activated",
    )


def test_dispatcher_agreement_completed():
    _assert_rendered(
        email_service.render_notification_email(
            "agreement_completed", "You own it", "msg", "Ada",
            {
                "asset_title": "Toyota Camry",
                "reference": "ABCDEF12",
                "total_paid": 10_000_000,
                "completed_date": "Jan 1, 2026",
                "asset_noun": "Car",
            },
        ),
        "Toyota Camry", label="dispatch:agreement_completed",
    )


def test_dispatcher_payment_successful_order():
    _assert_rendered(
        email_service.render_notification_email(
            "payment_successful", "Order Payment Confirmed", "msg", "Ada",
            {
                "context": "order",
                "order_id": "abcdef123456",
                "reference": "ABCDEF12",
                "amount": 5000,
                "amount_paid": 5000,
                "remaining_balance": 0,
                "total_amount": 5000,
            },
        ),
        "ABCDEF12", label="dispatch:payment_successful:order",
    )


def test_dispatcher_installment_paid():
    _assert_rendered(
        email_service.render_notification_email(
            "installment_paid", "Installment Payment Received", "msg", "Ada",
            {
                "context": "installment",
                "order_id": "abcdef123456",
                "reference": "ABCDEF12",
                "amount": 2000,
                "amount_paid": 5000,
                "remaining_balance": 1000,
                "total_amount": 6000,
            },
        ),
        "ABCDEF12", label="dispatch:installment_paid",
    )


def test_dispatcher_payment_refunded():
    _assert_rendered(
        email_service.render_notification_email(
            "payment_refunded", "Payment Refunded", "msg", "Ada",
            {"amount": 5000, "reason": "Duplicate charge", "reference": "ABCDEF12"},
        ),
        "Duplicate charge", label="dispatch:payment_refunded",
    )


def test_dispatcher_payment_failed():
    _assert_rendered(
        email_service.render_notification_email(
            "payment_failed", "Recurring Payment Failed", "msg", "Ada",
            {
                "asset_title": "Toyota Camry",
                "reference": "ABCDEF12",
                "amount": 500_000,
                "reason": "Insufficient funds",
                "next_attempt": "Feb 1, 2026",
            },
        ),
        "Toyota Camry", label="dispatch:payment_failed",
    )


def test_dispatcher_installment_defaulted():
    _assert_rendered(
        email_service.render_notification_email(
            "installment_defaulted", "Agreement Defaulted", "msg", "Ada",
            {
                "asset_title": "Toyota Camry",
                "reference": "ABCDEF12",
                "overdue_amount": 500_000,
                "due_date": "Jan 1, 2026",
                "grace_days": 3,
            },
        ),
        "Toyota Camry", label="dispatch:installment_defaulted",
    )


def test_dispatcher_inspection_rejected():
    _assert_rendered(
        email_service.render_notification_email(
            "inspection_rejected", "Inspection Missed", "msg", "Ada",
            {
                "asset_title": "Toyota Camry",
                "inspection_date": "Jan 1, 2026",
                "reason": "expired",
            },
        ),
        "Toyota Camry", label="dispatch:inspection_rejected",
    )


def test_dispatcher_order_confirmed():
    _assert_rendered(
        email_service.render_notification_email(
            "order_confirmed", "Order Confirmed", "msg", "Ada",
            {
                "order_id": "abcdef123456",
                "items_summary": "2× Phone",
                "total_amount": 2000,
                "delivery_type": "delivery",
                "delivery_fee": 1000,
                "estimated_delivery": "Feb 1, 2026",
            },
        ),
        "2× Phone", label="dispatch:order_confirmed",
    )


def test_dispatcher_order_processing():
    _assert_rendered(
        email_service.render_notification_email(
            "order_processing", "Order Processing", "msg", "Ada",
            {"order_id": "abcdef123456", "total_amount": 2000, "notes": "Packing"},
        ),
        "Processing", label="dispatch:order_processing",
    )


def test_dispatcher_order_cancelled():
    _assert_rendered(
        email_service.render_notification_email(
            "order_cancelled", "Order Cancelled", "msg", "Ada",
            {"order_id": "abcdef123456", "total_amount": 2000, "reason": "Out of stock"},
        ),
        "Out of stock", label="dispatch:order_cancelled",
    )


def test_dispatcher_installment_due():
    _assert_rendered(
        email_service.render_notification_email(
            "payment_reminder", "Upcoming Installment Reminder", "msg", "Ada",
            {
                "asset_title": "Toyota Camry",
                "amount_due": 500_000,
                "due_date": "Feb 1, 2026",
                "days_left": 3,
                "remaining_balance": 7_500_000,
            },
        ),
        "Toyota Camry", label="dispatch:installment_due",
    )


# ---------------------------------------------------------------------------
# Generic fallback hardening
# ---------------------------------------------------------------------------

def test_generic_fallback_drops_internal_keys_and_formats_money():
    html, text = _assert_rendered(
        email_service.render_notification_email(
            "some_unknown_event", "Something Happened", "A message", "Ada",
            {
                "user_id": "internal-user",
                "updated_by": "internal-admin",
                "old_status": "pending",
                "new_status": "processing",
                "dispute_event": "updated",
                "context": "order",
                "total_amount": 1234.5,
            },
        ),
        "₦1,234.50", label="generic",
    )
    for banned in ("internal-user", "internal-admin", "Old Status", "New Status", "Dispute Event"):
        assert banned not in html, f"generic fallback leaked {banned!r}"


def test_dispatcher_survives_bad_template_value():
    # A non-numeric days_left must not raise into the caller; dispatcher falls back.
    html, text = email_service.render_notification_email(
        "payment_reminder", "Reminder", "msg", "Ada",
        {
            "asset_title": "Toyota Camry",
            "amount_due": "not-a-number",
            "due_date": "Feb 1, 2026",
            "days_left": "not-an-int",
        },
    )
    assert html.strip() and text.strip()


# ---------------------------------------------------------------------------
# Standalone runner
# ---------------------------------------------------------------------------

def _run_all():
    failures = []
    tests = [
        (name, fn) for name, fn in sorted(globals().items())
        if name.startswith("test_") and callable(fn)
    ]
    for name, fn in tests:
        try:
            fn()
            print(f"PASS {name}")
        except Exception as exc:  # noqa: BLE001
            failures.append((name, exc))
            print(f"FAIL {name}: {exc}")
    print(f"\n{len(tests) - len(failures)}/{len(tests)} passed")
    if failures:
        raise SystemExit(1)


if __name__ == "__main__":
    _run_all()
