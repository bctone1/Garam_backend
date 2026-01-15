# app/endpoints/notification.py
from __future__ import annotations

from typing import Optional, List

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from database.session import get_db
from crud import notification as notif_crud
from models.inquiry import Notification
from schemas.notification import (
    NotificationResponse,
    NotificationUnreadCountResponse,
    NotificationMarkReadIn,
    NotificationMarkReadResponse,
    NotificationEventType,
)

router = APIRouter(prefix="/notifications", tags=["웹소켓 알림"])


# 1) 알림 목록
@router.get("", response_model=List[NotificationResponse])
def list_notifications(
    recipient_admin_id: int = Query(..., description="수신 관리자 id"),
    unread_only: bool = Query(False),
    offset: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=200),
    event_type: Optional[NotificationEventType] = Query(None),
    db: Session = Depends(get_db),
):
    rows = notif_crud.list_notifications(
        db,
        recipient_admin_id=recipient_admin_id,
        unread_only=unread_only,
        offset=offset,
        limit=limit,
        event_type=event_type,
    )
    return [NotificationResponse(**notif_crud.serialize_notification(r)) for r in rows]


# 3) 배지 숫자
@router.get("/unread-count", response_model=NotificationUnreadCountResponse)
def get_unread_count(
    recipient_admin_id: int = Query(..., description="수신 관리자 id"),
    event_type: Optional[NotificationEventType] = Query(None),
    db: Session = Depends(get_db),
):
    cnt = notif_crud.unread_count(db, recipient_admin_id=recipient_admin_id, event_type=event_type)
    return NotificationUnreadCountResponse(unread_count=cnt)


# 2) 알림 읽음 처리
@router.post("/{notification_id}/read", response_model=NotificationMarkReadResponse)
def mark_read(
    notification_id: int,
    payload: NotificationMarkReadIn,
    db: Session = Depends(get_db),
):
    ok = notif_crud.mark_read(
        db,
        notification_id=notification_id,
        recipient_admin_id=payload.recipient_admin_id,
    )
    if not ok:
        raise HTTPException(status_code=404, detail="notification not found")

    # REST 응답도 맞춰주기 위해 여기서 한번 더 계산(정합성 우선)
    cnt = notif_crud.unread_count(db, recipient_admin_id=payload.recipient_admin_id)
    return NotificationMarkReadResponse(
        ok=True,
        notification_id=notification_id,
        read_at=None,  # 필요하면 notif_crud가 read_at을 리턴하도록 확장 가능
        unread_count=cnt,
    )
