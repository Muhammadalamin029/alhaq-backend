from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import HTMLResponse
from sqlalchemy.orm import Session, joinedload
from sqlalchemy import desc, or_
from typing import Optional
from uuid import UUID

from db.session import get_db
from core.auth import role_required
from core.model import ExternalPayment
from core.external_payment_service import (
    create_external_payment,
    set_external_payment_pdf,
)
from core.logging_config import get_logger, log_error
from schemas.external_payment import (
    ExternalPaymentCreate,
    ExternalPaymentCreateResponse,
    ExternalPaymentOut,
    ExternalPaymentPdfUpload,
)

logger = get_logger("routers.admin_external_payments")
router = APIRouter()


def _serialize(payment: ExternalPayment) -> dict:
    return {
        "id": payment.id,
        "receipt_number": payment.receipt_number,
        "payer_name": payment.payer_name,
        "payer_email": payment.payer_email,
        "payer_phone": payment.payer_phone,
        "buyer_id": payment.buyer_id,
        "amount": payment.amount,
        "channel": payment.channel,
        "status": payment.status,
        "notes": payment.notes,
        "paid_at": payment.paid_at,
        "recorded_by": payment.recorded_by,
        "pdf_url": payment.pdf_url,
        "created_at": payment.created_at,
        "items": [
            {
                "id": i.id,
                "name": i.name,
                "description": i.description,
                "quantity": i.quantity,
                "unit_price": i.unit_price,
            }
            for i in (payment.items or [])
        ],
    }


@router.post("", response_model=ExternalPaymentCreateResponse,
             status_code=status.HTTP_201_CREATED)
async def record_external_payment(
    payload: ExternalPaymentCreate,
    admin=Depends(role_required(["admin"])),
    db: Session = Depends(get_db),
):
    """Record an offline sale (cash / bank transfer / POS) for anyone.

    Step 1 of 2: creates the ledger row and returns the receipt number.
    The FE then generates the PDF, uploads it to Cloudinary, and calls
    `PUT /{id}/pdf`.
    """
    try:
        payment = create_external_payment(
            db, payload, recorded_by=UUID(str(admin["id"])))
        payment = (
            db.query(ExternalPayment)
            .options(joinedload(ExternalPayment.items))
            .filter(ExternalPayment.id == payment.id)
            .first()
        )
        data = ExternalPaymentOut.model_validate(_serialize(payment)).model_dump()
        # Re-attach UUIDs lost in dict round-trip
        data["id"] = payment.id
        data["buyer_id"] = payment.buyer_id
        data["recorded_by"] = payment.recorded_by
        data["items"] = [
            {**d, "id": i.id}
            for d, i in zip(data["items"], payment.items or [])
        ]
        try:
            from core.system_settings_service import system_settings_service
            channel_label = {"cash": "Cash", "bank_transfer": "Bank Transfer",
                             "pos": "POS"}.get(payment.channel, payment.channel)
            system_settings_service.notify_admins(
                db=db,
                event_key="system_alert",
                title=f"External Payment Recorded — ₦{payment.amount:,.2f}",
                message=(
                    f"{channel_label} payment of ₦{payment.amount:,.2f} from "
                    f"{payment.payer_name} ({payment.payer_email}) recorded by "
                    f"{admin.get('email', 'admin')} "
                    f"({payment.receipt_number})."
                ),
                data={"external_payment_id": str(payment.id),
                      "receipt_number": payment.receipt_number,
                      "amount": float(payment.amount or 0),
                      "recorded_by": str(payment.recorded_by)},
                priority="medium",
            )
        except Exception as notify_exc:
            log_error(logger, "Non-fatal: admin alert failed for "
                              f"{payment.receipt_number}", notify_exc)
        return ExternalPaymentCreateResponse(
            message="External payment recorded",
            data=ExternalPaymentOut(**data),
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        log_error(logger, "Failed to record external payment", e)
        raise HTTPException(status_code=500,
                            detail="Failed to record external payment")


@router.put("/{payment_id}/pdf")
async def attach_receipt_pdf(
    payment_id: UUID,
    payload: ExternalPaymentPdfUpload,
    admin=Depends(role_required(["admin"])),
    db: Session = Depends(get_db),
):
    """Step 2 of 2: attach the Cloudinary PDF URL and optionally email it."""
    try:
        payment = set_external_payment_pdf(db, payment_id, payload.pdf_url)
    except LookupError:
        raise HTTPException(status_code=404,
                            detail="External payment not found")
    except Exception as e:
        log_error(logger, f"Failed to attach PDF for {payment_id}", e)
        raise HTTPException(status_code=500, detail="Failed to attach PDF")

    emailed = False
    if payload.send_receipt:
        try:
            from core.tasks import send_external_receipt_email
            send_external_receipt_email.delay(
                str(payment.id),
                payload.to_email_override or payment.payer_email,
            )
            emailed = True
        except Exception as e:
            log_error(logger, f"Failed to enqueue receipt email for {payment_id}", e)

    return {"success": True,
            "message": "Receipt PDF attached" + (
                " and email queued" if emailed else ""),
            "data": _serialize(payment)}


@router.post("/{payment_id}/send-receipt")
async def resend_receipt(
    payment_id: UUID,
    body: Optional[dict] = None,
    admin=Depends(role_required(["admin"])),
    db: Session = Depends(get_db),
):
    """Resend the stored Cloudinary PDF to the payer (or an override email)."""
    payment = (
        db.query(ExternalPayment).filter(ExternalPayment.id == payment_id).first()
    )
    if not payment:
        raise HTTPException(status_code=404,
                            detail="External payment not found")
    if not payment.pdf_url:
        raise HTTPException(status_code=400,
                            detail="No receipt PDF attached yet")
    to_email = (body or {}).get("email") or payment.payer_email
    try:
        from core.tasks import send_external_receipt_email
        send_external_receipt_email.delay(str(payment.id), to_email)
    except Exception as e:
        log_error(logger, f"Failed to enqueue receipt email for {payment_id}", e)
        raise HTTPException(status_code=500, detail="Failed to queue email")
    return {"success": True, "message": f"Receipt email queued to {to_email}"}


@router.get("")
async def list_external_payments(
    admin=Depends(role_required(["admin"])),
    db: Session = Depends(get_db),
    search: Optional[str] = Query(None),
    channel: Optional[str] = Query(None, pattern="^(cash|bank_transfer|pos)$"),
    page: int = Query(1, ge=1),
    limit: int = Query(20, ge=1, le=100),
):
    query = db.query(ExternalPayment).options(
        joinedload(ExternalPayment.items))
    if channel:
        query = query.filter(ExternalPayment.channel == channel)
    if search:
        like = f"%{search.strip()}%"
        query = query.filter(or_(
            ExternalPayment.receipt_number.ilike(like),
            ExternalPayment.payer_name.ilike(like),
            ExternalPayment.payer_email.ilike(like),
        ))
    total = query.count()
    rows = (query.order_by(desc(ExternalPayment.created_at))
            .offset((page - 1) * limit).limit(limit).all())
    return {
        "success": True,
        "message": "External payments retrieved",
        "data": [_serialize(r) for r in rows],
        "pagination": {
            "page": page, "limit": limit,
            "total_pages": (total + limit - 1) // limit,
            "has_next": page * limit < total, "has_prev": page > 1,
        },
        "total": total,
    }


@router.get("/{payment_id}/receipt/html", response_class=HTMLResponse)
async def get_external_receipt_html(
    payment_id: UUID,
    admin=Depends(role_required(["admin"])),
    db: Session = Depends(get_db),
):
    """Render the site's normal receipt HTML for an external payment."""
    from core.external_receipt_service import render_external_receipt_html
    html = render_external_receipt_html(db, payment_id)
    if not html:
        raise HTTPException(status_code=404,
                            detail="External payment not found")
    return HTMLResponse(content=html)


@router.get("/{payment_id}/receipt.pdf")
async def get_external_receipt_pdf(
    payment_id: UUID,
    admin=Depends(role_required(["admin"])),
    db: Session = Depends(get_db),
):
    """Download an external payment receipt as a server-generated vector PDF."""
    from fastapi.responses import Response
    from core.fpdf_receipt_service import render_external_receipt_pdf

    pdf_bytes = render_external_receipt_pdf(db, payment_id)
    if not pdf_bytes:
        raise HTTPException(status_code=404,
                            detail="External payment not found")
    payment = (
        db.query(ExternalPayment).filter(ExternalPayment.id == payment_id).first()
    )
    filename = "".join(
        c if (c.isalnum() or c in "._-") else "_"
        for c in (payment.receipt_number if payment else f"receipt-{payment_id}")
    )
    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{filename}.pdf"'},
    )


@router.get("/{payment_id}")
async def get_external_payment(
    payment_id: UUID,
    admin=Depends(role_required(["admin"])),
    db: Session = Depends(get_db),
):
    payment = (
        db.query(ExternalPayment)
        .options(joinedload(ExternalPayment.items))
        .filter(ExternalPayment.id == payment_id)
        .first()
    )
    if not payment:
        raise HTTPException(status_code=404,
                            detail="External payment not found")
    return {"success": True, "message": "External payment retrieved",
            "data": _serialize(payment)}


@router.delete("/{payment_id}")
async def delete_external_payment(
    payment_id: UUID,
    admin=Depends(role_required(["admin"])),
    db: Session = Depends(get_db),
):
    """Permanently delete an external payment and its line items.

    Line items are removed via the relationship cascade. A previously
    emailed/uploaded Cloudinary PDF is left orphaned (unguessable URL).
    """
    payment = (
        db.query(ExternalPayment).filter(ExternalPayment.id == payment_id).first()
    )
    if not payment:
        raise HTTPException(status_code=404,
                            detail="External payment not found")
    receipt_number = payment.receipt_number
    try:
        db.delete(payment)
        db.commit()
    except Exception as e:
        db.rollback()
        log_error(logger, f"Failed to delete external payment {payment_id}", e)
        raise HTTPException(status_code=500,
                            detail="Failed to delete external payment")
    logger.info(
        f"External payment {receipt_number} ({payment_id}) deleted "
        f"by admin {admin['id']}"
    )
    return {"success": True, "message": f"{receipt_number} deleted",
            "data": {"id": str(payment_id), "receipt_number": receipt_number}}
