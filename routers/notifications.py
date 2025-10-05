from fastapi import APIRouter, Depends, HTTPException, status, Query
from sqlalchemy.orm import Session
from typing import Optional

from core.auth import get_current_user
from db.session import get_db
from core.notifications_service import (
    get_notifications,
    mark_as_read,
    mark_all_as_read,
    bulk_mark_read,
    delete_notification,
    bulk_delete_notifications,
    update_preferences,
    get_or_create_preferences,
    create_notification,
    compute_stats,
    _parse_data,
)
from schemas.notification import (
    NotificationOut,
    NotificationsResponse,
    NotificationUpdate,
    BulkUpdateNotificationsRequest,
    NotificationPreferencesOut,
    NotificationPreferencesUpdate,
    NotificationStats,
    NotificationCreate,
)

router = APIRouter()


@router.get("/", response_model=NotificationsResponse)
def list_notifications(
    type: Optional[str] = Query(None),
    is_read: Optional[bool] = Query(None),
    priority: Optional[str] = Query(None),
    page: int = Query(1, ge=1),
    limit: int = Query(20, ge=1, le=100),
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    items, pagination, unread_count = get_notifications(
        db,
        current_user["id"],
        {"type": type, "is_read": is_read, "priority": priority, "page": page, "limit": limit},
    )

    # Manually map channels/data fields to match schema types
    def to_out(n):
        return {
            "id": str(n.id),
            "user_id": str(n.user_id),
            "type": n.type,
            "title": n.title,
            "message": n.message,
            "priority": n.priority,
            "channels": (n.channels or "in_app").split(","),
            "data": _parse_data(n.data),
            "is_read": bool(n.is_read),
            "is_sent": bool(n.is_sent),
            "created_at": str(n.created_at),
            "read_at": str(n.read_at) if n.read_at else None,
            "sent_at": str(n.sent_at) if n.sent_at else None,
            "expires_at": str(n.expires_at) if n.expires_at else None,
        }

    return {
        "notifications": [to_out(n) for n in items],
        "pagination": pagination,
        "unread_count": unread_count,
    }


@router.get("/stats", response_model=NotificationStats)
def get_stats(db: Session = Depends(get_db), current_user=Depends(get_current_user)):
    return compute_stats(db, current_user["id"])


@router.get("/preferences", response_model=NotificationPreferencesOut)
def get_preferences(db: Session = Depends(get_db), current_user=Depends(get_current_user)):
    prefs = get_or_create_preferences(db, current_user["id"])
    return _prefs_to_out(prefs)


@router.patch("/preferences", response_model=NotificationPreferencesOut)
def patch_preferences(
    payload: NotificationPreferencesUpdate,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    prefs = update_preferences(db, current_user["id"], payload.model_dump(exclude_unset=True))
    return _prefs_to_out(prefs)


@router.patch("/mark-all-read")
def patch_mark_all_read(
    payload: dict = None,  # Accept optional empty body
    db: Session = Depends(get_db), 
    current_user=Depends(get_current_user)
):
    count = mark_all_as_read(db, current_user["id"])
    return {"updated": count}


@router.patch("/{notification_id}")
def patch_notification(notification_id: str, payload: NotificationUpdate, db: Session = Depends(get_db), current_user=Depends(get_current_user)):
    if payload.is_read is True:
        ok = mark_as_read(db, current_user["id"], notification_id)
        if not ok:
            raise HTTPException(status_code=404, detail="Notification not found")
        return {"success": True}
    raise HTTPException(status_code=400, detail="No supported fields to update")


@router.patch("/bulk-update")
def patch_bulk_update(payload: BulkUpdateNotificationsRequest, db: Session = Depends(get_db), current_user=Depends(get_current_user)):
    if payload.is_read:
        updated = bulk_mark_read(db, current_user["id"], payload.notification_ids)
        return {"updated": updated}
    raise HTTPException(status_code=400, detail="Only is_read updates are supported")


@router.delete("/{notification_id}")
def remove_notification(notification_id: str, db: Session = Depends(get_db), current_user=Depends(get_current_user)):
    ok = delete_notification(db, current_user["id"], notification_id)
    if not ok:
        raise HTTPException(status_code=404, detail="Notification not found")
    return {"success": True}


@router.delete("/bulk-delete")
def remove_notifications(payload: BulkUpdateNotificationsRequest, db: Session = Depends(get_db), current_user=Depends(get_current_user)):
    deleted = bulk_delete_notifications(db, current_user["id"], payload.notification_ids)
    return {"deleted": deleted}


def _prefs_to_out(p):
    return {
        "id": str(p.id),
        "user_id": str(p.user_id),
        "email_notifications": {
            "order_updates": bool(p.email_order_updates),
            "payment_updates": bool(p.email_payment_updates),
            "account_updates": bool(p.email_account_updates),
            "promotional_offers": bool(p.email_promotional_offers),
            "system_announcements": bool(p.email_system_announcements),
        },
        "sms_notifications": {
            "order_updates": bool(p.sms_order_updates),
            "payment_updates": bool(p.sms_payment_updates),
            "account_updates": bool(p.sms_account_updates),
            "promotional_offers": False,
            "system_announcements": True,
        },
        "push_notifications": {
            "order_updates": bool(p.push_order_updates),
            "payment_updates": bool(p.push_payment_updates),
            "account_updates": bool(p.push_account_updates),
            "promotional_offers": bool(p.push_promotional_offers),
            "system_announcements": True,
        },
        "in_app_notifications": {
            "order_updates": bool(p.in_app_order_updates),
            "payment_updates": bool(p.in_app_payment_updates),
            "account_updates": bool(p.in_app_account_updates),
            "promotional_offers": bool(p.in_app_promotional_offers),
            "system_announcements": bool(p.in_app_system_announcements),
        },
        "created_at": str(p.created_at),
        "updated_at": str(p.updated_at),
    }


