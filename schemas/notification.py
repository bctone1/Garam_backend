from __future__ import annotations

from datetime import datetime
from typing import Optional, Literal, List

from pydantic import BaseModel


NotificationEventType = Literal["inquiry_new", "inquiry_assigned", "inquiry_completed"]


class NotificationInquiryMini(BaseModel):
    id: int
    business_name: str
    status: str
    inquiry_type: str
    created_at: datetime

    class Config:
        from_attributes = True


class NotificationResponse(BaseModel):
    id: int
    recipient_admin_id: int
    event_type: NotificationEventType
    inquiry_id: int
    actor_admin_id: Optional[int] = None

    created_at: datetime
    read_at: Optional[datetime] = None

    actor_name: Optional[str] = None
    inquiry: Optional[NotificationInquiryMini] = None

    title: str
    body: str
    deep_link: str  # 프론트 라우팅용 (예: /inquiries/123)

    class Config:
        from_attributes = True


class NotificationUnreadCountResponse(BaseModel):
    unread_count: int


class NotificationMarkReadIn(BaseModel):
    recipient_admin_id: int


class NotificationMarkReadResponse(BaseModel):
    ok: bool
    notification_id: int
    read_at: Optional[datetime] = None
    unread_count: int
