from sqlalchemy.orm import Session
from fastapi import HTTPException
from core.model import Dispute, User
from schemas.dispute import DisputeCreate, DisputeUpdate
from core.notifications_service import create_notification
from core.system_settings_service import system_settings_service
import logging

logger = logging.getLogger(__name__)


class DisputeService:

    def create_dispute(self, db: Session, user_id: str, data: DisputeCreate) -> Dispute:
        if not data.order_id and not data.agreement_id:
            raise HTTPException(status_code=400, detail="Must provide either order_id or agreement_id")

        dispute = Dispute(
            user_id=user_id,
            title=data.title,
            reason=data.reason,
            order_id=data.order_id,
            agreement_id=data.agreement_id,
            status="open"
        )
        db.add(dispute)
        db.commit()
        db.refresh(dispute)

        create_notification(db, {
            "user_id": str(user_id),
            "type": "system_announcement",
            "title": "Dispute Opened",
            "message": f"Your dispute '{data.title}' has been received and is under review.",
            "priority": "high",
            "channels": ["in_app", "email"],
            "data": {
                "dispute_id": str(dispute.id),
                "order_id": str(data.order_id) if data.order_id else None,
                "agreement_id": str(data.agreement_id) if data.agreement_id else None,
            },
        })

        system_settings_service.notify_admins(
            db=db,
            event_key="dispute",
            title="New Dispute Opened",
            message=f"A new dispute titled '{data.title}' was submitted.",
            data={"dispute_id": str(dispute.id), "user_id": str(user_id)},
            priority="high",
        )

        return dispute

    def update_dispute(self, db: Session, dispute_id: str, admin_id: str,
                       data: DisputeUpdate) -> Dispute:
        dispute = db.query(Dispute).filter(Dispute.id == dispute_id).first()
        if not dispute:
            raise HTTPException(status_code=404, detail="Dispute not found")

        if data.status:
            dispute.status = data.status
        if data.resolution_notes:
            dispute.resolution_notes = data.resolution_notes

        db.commit()
        db.refresh(dispute)

        is_resolved = dispute.status in ("resolved", "closed")
        create_notification(db, {
            "user_id": str(dispute.user_id),
            "type": "system_announcement",
            "title": "Dispute Resolved" if is_resolved else "Dispute Update",
            "message": (
                f"Your dispute '{dispute.title}' has been resolved."
                if is_resolved
                else f"Update on your dispute '{dispute.title}': status is now {dispute.status}."
            ),
            "priority": "high",
            "channels": ["in_app", "email"],
            "data": {
                "dispute_id": str(dispute.id),
                "resolved": is_resolved,
                "resolution": dispute.status,
                "resolution_notes": dispute.resolution_notes,
            },
        })

        system_settings_service.notify_admins(
            db=db,
            event_key="dispute",
            title="Dispute Updated",
            message=f"Dispute '{dispute.title}' is now {dispute.status}.",
            data={"dispute_id": str(dispute.id), "status": dispute.status,
                  "updated_by": admin_id},
            priority="medium",
        )

        return dispute

    def get_disputes(self, db: Session, user_id: str = None,
                     limit: int = 50, offset: int = 0):
        query = db.query(Dispute)
        if user_id:
            query = query.filter(Dispute.user_id == user_id)
        return query.order_by(Dispute.created_at.desc()).offset(offset).limit(limit).all()

    def get_dispute(self, db: Session, dispute_id: str):
        dispute = db.query(Dispute).filter(Dispute.id == dispute_id).first()
        if not dispute:
            raise HTTPException(status_code=404, detail="Dispute not found")
        return dispute


dispute_service = DisputeService()
