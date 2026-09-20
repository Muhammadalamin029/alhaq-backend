from sqlalchemy.orm import Session, joinedload
from sqlalchemy import desc
from uuid import UUID
from datetime import datetime
from typing import List, Optional, Tuple
from fastapi import HTTPException

from core.model import (
    FinancingApplication, FinancingApplicationDocument, FinancingDocumentRequirement, User
)
from core.status_constants import (
    FINANCING_APPLICATION_STATUS_PENDING_REVIEW,
    FINANCING_APPLICATION_STATUS_APPROVED,
    FINANCING_APPLICATION_STATUS_REJECTED,
    FINANCING_APPLICATION_STATUS_REVOKED,
)
from core.notifications_service import create_notification
from core.email_service import _ref
from core.system_settings_service import system_settings_service
from core.tasks import (
    send_financing_application_approved_email,
    send_financing_application_rejected_email,
    send_financing_application_revoked_email,
)
from schemas.financing import (
    FinancingApplicationSubmit,
    FinancingDocumentRequirementCreate,
    FinancingDocumentRequirementUpdate,
)


class FinancingService:
    # ---------------- Document Requirements (admin-configured) ----------------

    def list_active_document_requirements(self, db: Session) -> List[FinancingDocumentRequirement]:
        return (
            db.query(FinancingDocumentRequirement)
            .filter(FinancingDocumentRequirement.is_active == True)
            .order_by(FinancingDocumentRequirement.display_order)
            .all()
        )

    def list_all_document_requirements(self, db: Session) -> List[FinancingDocumentRequirement]:
        return db.query(FinancingDocumentRequirement).order_by(FinancingDocumentRequirement.display_order).all()

    def create_document_requirement(self, db: Session, data: FinancingDocumentRequirementCreate) -> FinancingDocumentRequirement:
        requirement = FinancingDocumentRequirement(**data.model_dump())
        db.add(requirement)
        db.commit()
        db.refresh(requirement)
        return requirement

    def update_document_requirement(self, db: Session, requirement_id: UUID, data: FinancingDocumentRequirementUpdate) -> FinancingDocumentRequirement:
        requirement = db.query(FinancingDocumentRequirement).filter(FinancingDocumentRequirement.id == requirement_id).first()
        if not requirement:
            raise HTTPException(status_code=404, detail="Document requirement not found")
        for field, value in data.model_dump(exclude_unset=True).items():
            setattr(requirement, field, value)
        db.commit()
        db.refresh(requirement)
        return requirement

    def set_document_requirement_active(self, db: Session, requirement_id: UUID, is_active: bool) -> FinancingDocumentRequirement:
        requirement = db.query(FinancingDocumentRequirement).filter(FinancingDocumentRequirement.id == requirement_id).first()
        if not requirement:
            raise HTTPException(status_code=404, detail="Document requirement not found")
        requirement.is_active = is_active
        db.commit()
        db.refresh(requirement)
        return requirement

    # ---------------- Applications ----------------

    def _get_latest(self, db: Session, user_id: UUID) -> Optional[FinancingApplication]:
        return (
            db.query(FinancingApplication)
            .options(joinedload(FinancingApplication.documents).joinedload(FinancingApplicationDocument.requirement))
            .filter(FinancingApplication.user_id == user_id)
            .order_by(desc(FinancingApplication.created_at))
            .first()
        )

    def get_my_application(self, db: Session, user_id: UUID) -> Optional[FinancingApplication]:
        return self._get_latest(db, user_id)

    def check_eligible(self, db: Session, user_id: UUID, payment_plan: str) -> None:
        """Gate for GeneralAgreement creation - called from both create_agreement and
        complete_inspection in asset_service. No-op for full_payment."""
        if payment_plan not in ("monthly", "installment"):
            return

        latest = self._get_latest(db, user_id)
        if not latest:
            raise HTTPException(
                status_code=400,
                detail="You must submit a financing application and be approved before choosing a monthly or installment plan.",
            )
        if latest.status == FINANCING_APPLICATION_STATUS_PENDING_REVIEW:
            raise HTTPException(status_code=400, detail="Your financing application is still under review.")
        if latest.status == FINANCING_APPLICATION_STATUS_REJECTED:
            reason = f" Reason: {latest.decision_reason}" if latest.decision_reason else ""
            raise HTTPException(status_code=400, detail=f"Your financing application was rejected.{reason} Please submit a new application.")
        if latest.status == FINANCING_APPLICATION_STATUS_REVOKED:
            reason = f" Reason: {latest.revocation_reason}" if latest.revocation_reason else ""
            raise HTTPException(status_code=400, detail=f"Your financing eligibility was revoked.{reason} Please submit a new application.")
        # status == approved -> eligible

    def submit_application(self, db: Session, user_id: UUID, data: FinancingApplicationSubmit) -> FinancingApplication:
        latest = self._get_latest(db, user_id)
        if latest and latest.status in (FINANCING_APPLICATION_STATUS_PENDING_REVIEW, FINANCING_APPLICATION_STATUS_APPROVED):
            raise HTTPException(
                status_code=400,
                detail=f"You already have a financing application that is {latest.status.replace('_', ' ')}.",
            )

        all_requirements = {r.id: r for r in self.list_all_document_requirements(db)}
        provided_ids = {doc.requirement_id for doc in data.documents}

        invalid = [str(doc.requirement_id) for doc in data.documents if doc.requirement_id not in all_requirements]
        if invalid:
            raise HTTPException(status_code=400, detail=f"Unknown document requirement id(s): {', '.join(invalid)}")

        missing = [
            r.name for r in all_requirements.values()
            if r.is_active and r.is_required and r.id not in provided_ids
        ]
        if missing:
            raise HTTPException(status_code=400, detail=f"Missing required documents: {', '.join(missing)}")

        application = FinancingApplication(
            user_id=user_id,
            employment_status=data.employment_status,
            employer_name=data.employer_name,
            job_title=data.job_title,
            monthly_income=data.monthly_income,
            employment_duration_months=data.employment_duration_months,
            additional_notes=data.additional_notes,
            status=FINANCING_APPLICATION_STATUS_PENDING_REVIEW,
        )
        db.add(application)
        db.flush()

        for doc in data.documents:
            db.add(FinancingApplicationDocument(
                application_id=application.id,
                requirement_id=doc.requirement_id,
                document_url=doc.document_url,
                original_filename=doc.original_filename,
            ))

        db.commit()
        db.refresh(application)

        create_notification(db, {
            "user_id": str(user_id),
            "type": "financing_application_submitted",
            "title": "Financing Application Submitted",
            "message": "Your financing application has been submitted and is pending review.",
            "priority": "medium",
        })

        system_settings_service.notify_admins(
            db=db,
            event_key="system_alert",
            title="New Financing Application",
            message="A customer has submitted a financing application for review.",
            data={"application_id": str(application.id)},
            priority="medium",
        )

        return application

    # ---------------- Admin review ----------------

    def list_applications(self, db: Session, status: Optional[str] = None, page: int = 1, limit: int = 20) -> Tuple[List[FinancingApplication], int]:
        query = db.query(FinancingApplication).options(
            joinedload(FinancingApplication.user).joinedload(User.profile),
            joinedload(FinancingApplication.documents).joinedload(FinancingApplicationDocument.requirement),
        )
        if status:
            query = query.filter(FinancingApplication.status == status)
        total = query.count()
        offset = (page - 1) * limit
        applications = query.order_by(desc(FinancingApplication.created_at)).offset(offset).limit(limit).all()
        return applications, total

    def get_application(self, db: Session, application_id: UUID) -> FinancingApplication:
        application = (
            db.query(FinancingApplication)
            .options(
                joinedload(FinancingApplication.user).joinedload(User.profile),
                joinedload(FinancingApplication.documents).joinedload(FinancingApplicationDocument.requirement),
            )
            .filter(FinancingApplication.id == application_id)
            .first()
        )
        if not application:
            raise HTTPException(status_code=404, detail="Financing application not found")
        return application

    def approve_application(self, db: Session, admin_id: UUID, application_id: UUID) -> FinancingApplication:
        application = self.get_application(db, application_id)
        if application.status != FINANCING_APPLICATION_STATUS_PENDING_REVIEW:
            raise HTTPException(status_code=400, detail="Only pending applications can be approved")

        application.status = FINANCING_APPLICATION_STATUS_APPROVED
        application.reviewed_by = admin_id
        application.reviewed_at = datetime.utcnow()
        db.commit()
        db.refresh(application)

        create_notification(db, {
            "user_id": str(application.user_id),
            "type": "financing_application_approved",
            "title": "Financing Application Approved",
            "message": "Your financing application has been approved. You can now select monthly or installment plans.",
            "priority": "high",
            "skip_email": True,  # dedicated approval email is queued below
        })

        user = db.query(User).filter(User.id == application.user_id).first()
        if user:
            send_financing_application_approved_email.delay(
                user.email,
                user.name,
                _ref(application.id),
                application.reviewed_at.strftime("%B %d, %Y") if application.reviewed_at else None,
            )

        return application

    def reject_application(self, db: Session, admin_id: UUID, application_id: UUID, reason: Optional[str]) -> FinancingApplication:
        if not reason:
            raise HTTPException(status_code=400, detail="A rejection reason is required")

        application = self.get_application(db, application_id)
        if application.status != FINANCING_APPLICATION_STATUS_PENDING_REVIEW:
            raise HTTPException(status_code=400, detail="Only pending applications can be rejected")

        application.status = FINANCING_APPLICATION_STATUS_REJECTED
        application.reviewed_by = admin_id
        application.reviewed_at = datetime.utcnow()
        application.decision_reason = reason
        db.commit()
        db.refresh(application)

        create_notification(db, {
            "user_id": str(application.user_id),
            "type": "financing_application_rejected",
            "title": "Financing Application Rejected",
            "message": f"Your financing application was rejected. Reason: {reason}",
            "priority": "high",
            "skip_email": True,  # dedicated rejection email is queued below
        })

        user = db.query(User).filter(User.id == application.user_id).first()
        if user:
            send_financing_application_rejected_email.delay(
                user.email,
                user.name,
                reason,
                _ref(application.id),
                application.reviewed_at.strftime("%B %d, %Y") if application.reviewed_at else None,
            )

        return application

    def revoke_application(self, db: Session, admin_id: UUID, application_id: UUID, reason: Optional[str]) -> FinancingApplication:
        if not reason:
            raise HTTPException(status_code=400, detail="A revocation reason is required")

        application = self.get_application(db, application_id)
        if application.status != FINANCING_APPLICATION_STATUS_APPROVED:
            raise HTTPException(status_code=400, detail="Only approved applications can be revoked")

        application.status = FINANCING_APPLICATION_STATUS_REVOKED
        application.revoked_by = admin_id
        application.revoked_at = datetime.utcnow()
        application.revocation_reason = reason
        db.commit()
        db.refresh(application)

        create_notification(db, {
            "user_id": str(application.user_id),
            "type": "financing_application_revoked",
            "title": "Financing Eligibility Revoked",
            "message": f"Your financing eligibility has been revoked. Reason: {reason}",
            "priority": "urgent",
            "skip_email": True,  # dedicated revocation email is queued below
        })

        user = db.query(User).filter(User.id == application.user_id).first()
        if user:
            send_financing_application_revoked_email.delay(
                user.email,
                user.name,
                reason,
                _ref(application.id),
                application.revoked_at.strftime("%B %d, %Y") if application.revoked_at else None,
            )

        return application


financing_service = FinancingService()
