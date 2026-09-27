"""Seed/reset legal documents so the new Play-ready defaults take effect.

The canonical Terms (12 sections) and Privacy (12 sections) live in
  alhaq-frontend/src/content/legalDefaults.ts
and are served as fallback by /privacy and /legal when the DB row is empty.

This script deletes stale legal_documents rows (old 3/4-section content) so
public GET /public/legal/{terms,privacy} returns nulls and the frontend
renders the new defaults. An admin can then open /admin/settings?tab=legal
and press Save to persist the rendered HTML + effective date.

Usage:
    .venv/bin/python scripts/seed_legal.py --reset
    .venv/bin/python scripts/seed_legal.py --reset --effective-date 2026-10-05
"""

import argparse
import os
import sys
from datetime import date

# Allow running as `python scripts/seed_legal.py` from any cwd: the backend
# root (parent of scripts/) must be importable for `core` and `db`.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.model import LegalDocument
from db.session import SessionLocal


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--reset", action="store_true", help="Delete stale legal rows so FE defaults render")
    parser.add_argument("--effective-date", default="2026-10-05")
    args = parser.parse_args()

    if not args.reset:
        print("Nothing to do. Pass --reset to clear stale legal_documents rows.")
        return

    eff = date.fromisoformat(args.effective_date)
    db = SessionLocal()
    try:
        deleted = db.query(LegalDocument).filter(LegalDocument.slug.in_(["terms", "privacy"])).delete(synchronize_session=False)
        db.commit()
        print(f"Cleared {deleted} stale legal row(s). Effective date for next admin Save: {eff.isoformat()}")
        print("Frontend /legal, /privacy, /account-deletion now render the new Play-ready defaults.")
    finally:
        db.close()


if __name__ == "__main__":
    main()
