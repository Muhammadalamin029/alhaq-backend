"""WhatsApp number -> store account link.

A row exists only AFTER the customer proved they own the account's email
(OTP). Never write a row before verification.

Tonight the table is created automatically at startup (create_all with
checkfirst). When the backend repo is available, add a proper Alembic
migration for `whatsapp_links` and import this model in core/model.py so
autogenerate knows about it.
"""

import logging

from sqlalchemy import TIMESTAMP, UUID, Column, ForeignKey, String, func

from db.session import Base, engine

logger = logging.getLogger("lel_store_backend.whatsapp")


class WhatsAppLink(Base):
    __tablename__ = "whatsapp_links"

    # Digits only, no "+", e.g. 2348012345678 (the "from" value WhatsApp sends).
    phone = Column(String(32), primary_key=True)
    user_id = Column(UUID, ForeignKey("users.id"), nullable=False, index=True)
    created_at = Column(TIMESTAMP, server_default=func.current_timestamp())


def ensure_whatsapp_tables() -> None:
    try:
        WhatsAppLink.__table__.create(bind=engine, checkfirst=True)
    except Exception:  # pragma: no cover - startup safety net
        logger.exception("Could not create whatsapp_links table")
