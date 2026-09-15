"""
Run with:  python test_emails.py
Sends one of each email type to mmuhammadalameen9@gmail.com.
"""
import sys
import os

# Ensure the backend root is on sys.path so imports work
sys.path.insert(0, os.path.dirname(__file__))

TEST_EMAIL = "mmuhammadalameen9@gmail.com"

from core.email_service import email_service

results: list[tuple[str, bool]] = []


def send(name: str, subject: str, html: str, text: str):
    ok = email_service.send_email_sync(TEST_EMAIL, subject, html, text)
    status = "✅ SENT" if ok else "❌ FAILED"
    results.append((name, ok))
    print(f"  {status}  {name}")
    return ok


print(f"\n{'='*60}")
print(f"  Sending {12} test emails to {TEST_EMAIL}")
print(f"{'='*60}\n")

# 1. Email Verification
h, t = email_service.render_verification_email("John Doe", "847261")
send("Verification Code", f"Verify your email — {email_service.from_name}", h, t)

# 2. Password Reset
h, t = email_service.render_password_reset_email("John Doe", "392847")
send("Password Reset", f"Password Reset — {email_service.from_name}", h, t)

# 3. Welcome
h, t = email_service.render_welcome_email("John Doe")
send("Welcome Email", f"Welcome to {email_service.from_name}!", h, t)

# 4. Login Notification
h, t = email_service.render_login_email(
    "John Doe",
    login_time="03 Jun 2026, 09:45 AM UTC",
    ip_address="102.88.64.21",
    device="Chrome on Windows 11",
)
send("Login Alert", f"New Sign-In Detected — {email_service.from_name}", h, t)

# 5. KYC Approved
h, t = email_service.render_kyc_approved_email("Premium Auto Lagos", "03 Jun 2026")
send("KYC Approved", f"KYC Approved — {email_service.from_name}", h, t)

# 6. KYC Rejected
h, t = email_service.render_kyc_rejected_email(
    "Premium Auto Lagos",
    reason="Business registration certificate could not be verified.",
)
send("KYC Rejected", f"KYC Verification Required — {email_service.from_name}", h, t)

# 7. Payout Requested
h, t = email_service.render_payout_requested_email(
    "Premium Auto Lagos",
    amount="₦250,000.00",
    bank_name="Zenith Bank",
    account_number="2034567890",
)
send("Payout Requested", f"Payout Request Received — {email_service.from_name}", h, t)

# 8. Payout Completed
h, t = email_service.render_payout_completed_email(
    "Premium Auto Lagos",
    amount="₦250,000.00",
    bank_name="Zenith Bank",
    reference="PAYOUT_3F9A2B1C",
)
send("Payout Completed", f"Payout Successful — {email_service.from_name}", h, t)

# 9. Payout Failed
h, t = email_service.render_payout_failed_email(
    "Premium Auto Lagos",
    amount="₦250,000.00",
    reason="Invalid account number — account does not match bank records.",
)
send("Payout Failed", f"Payout Failed — {email_service.from_name}", h, t)

# 10. Inspection Confirmed
h, t = email_service.render_inspection_confirmed_email(
    user_name="Aminu Bello",
    asset_title="Toyota Camry 2022 — Pearl White",
    inspection_date="Saturday, 07 Jun 2026 at 11:00 AM",
    location="Victoria Island, Lagos",
    seller_name="Premium Auto Lagos",
    seller_contact="08031234567",
)
send("Inspection Confirmed", f"Inspection Confirmed — {email_service.from_name}", h, t)

# 11. Agreement Approved
h, t = email_service.render_agreement_approved_email(
    user_name="Aminu Bello",
    asset_title="Toyota Camry 2022",
    total_price="₦18,500,000.00",
    remaining="₦16,650,000.00",
    next_due="07 Jul 2026",
    monthly="₦1,385,000.00",
)
send("Agreement Approved", f"Agreement Approved — {email_service.from_name}", h, t)

# 12. Dispute Opened
h, t = email_service.render_dispute_opened_email(
    user_name="Aminu Bello",
    dispute_title="Item not as described",
    reference="DIS-3F9A2B",
    order_or_agreement_id="ORD-20260603-001",
)
send("Dispute Opened", f"Dispute Opened — {email_service.from_name}", h, t)

print(f"\n{'='*60}")
passed = sum(1 for _, ok in results if ok)
print(f"  Results: {passed}/{len(results)} sent successfully")
if passed < len(results):
    failed = [name for name, ok in results if not ok]
    print(f"  Failed:  {', '.join(failed)}")
print(f"{'='*60}\n")
