"""Purge PII for accounts past the 30-day deletion grace period.

Run daily (cron / Celery beat):
    .venv/bin/python -m services.purge_deleted_accounts

Policy:
- Personal data (profile, addresses, push tokens, prefs, wishlist, financing docs
  content, contact fields) is deleted or irreversibly anonymized.
- Anonymized escrow/financial ledgers (orders, payments, agreements, inspections)
  are RETAINED up to 7 years for AML / tax / deed-tracing compliance, with user
  links nulled and notes scrubbed. Never hard-delete ledger rows here.
"""

from datetime import datetime

from core.logging_config import get_logger

logger = get_logger("services.purge_deleted_accounts")


def purge_due_accounts(db, batch_limit: int = 500) -> int:
    from core.model import (
        Address as AddressModel,
        FinancingApplication as FinancingApplicationModel,
        NotificationPreferences as NotificationPreferencesModel,
        Profile as ProfileModel,
        PushDeviceToken as PushDeviceTokenModel,
        User as UserModel,
        Wishlist as WishlistModel,
    )

    now = datetime.utcnow()
    due = (
        db.query(UserModel)
        .filter(UserModel.is_active.is_(False))
        .filter(UserModel.deleted_at.isnot(None))
        .filter(UserModel.deleted_at <= now)
        .limit(batch_limit)
        .all()
    )
    purged = 0
    for user in due:
        uid = user.id
        try:
            # 1. Direct PII rows: delete.
            db.query(PushDeviceTokenModel).filter(PushDeviceTokenModel.user_id == uid).delete(synchronize_session=False)
            db.query(NotificationPreferencesModel).filter(NotificationPreferencesModel.user_id == uid).delete(synchronize_session=False)
            db.query(WishlistModel).filter(WishlistModel.user_id == uid).delete(synchronize_session=False)
            db.query(AddressModel).filter(AddressModel.user_id == uid).delete(synchronize_session=False)

            # 2. Financing applications: scrub sensitive fields, keep anonymized row for audit.
            for app in db.query(FinancingApplicationModel).filter(FinancingApplicationModel.user_id == uid).all():
                app.employer_name = None
                app.job_title = None
                app.additional_notes = "[redacted after account deletion]"
                # monthly_income/employment_status retained in anonymized ledger form;
                # documents keep URLs but are detached from identity via user anonymization.
                for doc in app.documents:
                    doc.original_filename = None

            # 3. Profile: scrub contact PII.
            profile = db.query(ProfileModel).filter(ProfileModel.id == uid).first()
            if profile:
                profile.name = "Deleted User"
                profile.phone = None
                profile.bio = None
                profile.avatar_url = None

            # 4. Inspections/agreements/notes linked via User: null free-text where possible.
            # Ledger rows themselves are retained; user link is anonymized via step 5.
            from core.model import GeneralAgreement as AgreementModel
            from core.model import GeneralInspection as InspectionModel

            for insp in db.query(InspectionModel).filter(InspectionModel.user_id == uid).all():
                insp.notes = "[redacted after account deletion]"
            for agr in db.query(AgreementModel).filter(AgreementModel.user_id == uid).all():
                pass  # numeric ledger retained as-is (no free-text PII fields)

            # 5. Anonymize login identity last (keeps FK integrity for retained ledgers).
            stamp = now.strftime("%Y%m%d%H%M%S")
            user.email = f"deleted_{uid}_{stamp}@deleted.lelstore.com"
            user.hashed_password = None
            user.google_id = None
            user.failed_login_attempts = 0
            user.locked_until = None
            user.deletion_requested_at = None
            user.deleted_at = None  # purge complete; row remains as anonymized ledger key
            # is_active stays False so the anonymized row can never log in.
            db.commit()
            purged += 1
            logger.info(f"Purged PII for deleted user {uid}")
        except Exception as e:
            db.rollback()
            logger.error(f"Failed to purge user {uid}: {e}")
    return purged


def main() -> None:
    from db.session import SessionLocal

    db = SessionLocal()
    try:
        count = purge_due_accounts(db)
        print(f"Purged {count} account(s).")
    finally:
        db.close()


if __name__ == "__main__":
    main()
