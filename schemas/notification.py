from typing import List, Optional, Dict, Any
from pydantic import BaseModel, Field


class NotificationBase(BaseModel):
    type: str
    title: str
    message: str
    priority: Optional[str] = Field(default="low")
    channels: Optional[List[str]] = Field(default_factory=lambda: ["in_app"])
    data: Optional[Dict[str, Any]] = None
    expires_at: Optional[str] = None


class NotificationCreate(NotificationBase):
    user_id: str


class NotificationUpdate(BaseModel):
    is_read: Optional[bool] = None


class NotificationOut(BaseModel):
    id: str
    user_id: str
    type: str
    title: str
    message: str
    priority: str
    channels: List[str]
    data: Optional[Dict[str, Any]]
    is_read: bool
    is_sent: bool
    created_at: str
    read_at: Optional[str]
    sent_at: Optional[str]
    expires_at: Optional[str]

    class Config:
        from_attributes = True


class NotificationFilters(BaseModel):
    type: Optional[str] = None
    is_read: Optional[bool] = None
    priority: Optional[str] = None
    page: int = 1
    limit: int = 20


class NotificationsResponse(BaseModel):
    notifications: List[NotificationOut]
    pagination: Dict[str, int]
    unread_count: int


class BulkUpdateNotificationsRequest(BaseModel):
    notification_ids: List[str]
    is_read: bool


class NotificationPreferencesChannels(BaseModel):
    order_updates: bool = True
    payment_updates: bool = True
    account_updates: bool = True
    promotional_offers: bool = False
    system_announcements: bool = True


class NotificationPreferencesOut(BaseModel):
    id: str
    user_id: str
    email_notifications: NotificationPreferencesChannels
    sms_notifications: NotificationPreferencesChannels
    push_notifications: NotificationPreferencesChannels
    in_app_notifications: NotificationPreferencesChannels
    created_at: str
    updated_at: str

    class Config:
        from_attributes = True


class NotificationPreferencesUpdate(BaseModel):
    email_notifications: Optional[NotificationPreferencesChannels] = None
    sms_notifications: Optional[NotificationPreferencesChannels] = None
    push_notifications: Optional[NotificationPreferencesChannels] = None
    in_app_notifications: Optional[NotificationPreferencesChannels] = None


class NotificationStats(BaseModel):
    total_notifications: int
    unread_count: int
    read_count: int
    by_type: Dict[str, int]
    by_priority: Dict[str, int]
    recent_activity: Dict[str, int]


