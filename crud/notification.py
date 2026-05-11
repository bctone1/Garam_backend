# crud/notification.py
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, List, Literal, Optional, Tuple

from sqlalchemy import and_, func, select, update
from sqlalchemy.orm import Session, joinedload

from models.inquiry import Notification
from service.ws_manager import ws_manager

EventType = Literal["inquiry_new", "inquiry_assigned", "inquiry_completed"]


# ======================
# UI message helpers
# ======================
def _build_message(
    *,
    event_type: str,
    business_name: Optional[str],
    actor_name: Optional[str],
) -> tuple[str, str]:
    bn = business_name or "해당 업체"
    actor = actor_name or "관리자"

    if event_type == "inquiry_new":
        return "새 문의 접수", f"{bn} 로 문의가 접수됐습니다."
    if event_type == "inquiry_assigned":
        return "문의 할당", f"{actor}에서  {bn} 님의 문의가 할당됐습니다."
    if event_type == "inquiry_completed":
        return "문의 완료", f"{actor} 에서 {bn} 문의를 처리했습니다."
    return "알림", f"{bn} 관련 알림이 도착했습니다."

def _unread_count(db: Session, recipient_admin_id: int, event_type: Optional[EventType] = None) -> int:
    stmt = (
        select(func.count())
        .select_from(Notification)
        .where(
            and_(
                Notification.recipient_admin_id == recipient_admin_id,
                Notification.read_at.is_(None),
            )
        )
    )
    if event_type:
        stmt = stmt.where(Notification.event_type == event_type)
    return int(db.execute(stmt).scalar_one() or 0)


def serialize_notification(n: Notification) -> Dict[str, Any]:
    inquiry = getattr(n, "inquiry", None)
    actor = getattr(n, "actor", None)

    actor_name = actor.name if actor else None
    business_name = getattr(inquiry, "business_name", None) if inquiry else None

    title, body = _build_message(
        event_type=str(getattr(n, "event_type", "")),
        business_name=business_name,
        actor_name=actor_name,
    )

    return {
        "id": n.id,
        "recipient_admin_id": n.recipient_admin_id,
        "event_type": n.event_type,
        "inquiry_id": n.inquiry_id,
        "actor_admin_id": n.actor_admin_id,

        "created_at": n.created_at,
        "read_at": n.read_at,

        "actor_name": actor_name,

        "inquiry": (
            {
                "id": inquiry.id,
                "business_name": inquiry.business_name,
                "status": inquiry.status,
                "inquiry_type": getattr(inquiry, "inquiry_type", "other"),
                "created_at": inquiry.created_at,
            }
            if inquiry
            else None
        ),

        "title": title,
        "body": body,
        "deep_link": f"/inquiries/{n.inquiry_id}",
    }


def list_notifications(
    db: Session,
    *,
    recipient_admin_id: int,
    unread_only: bool = False,
    offset: int = 0,
    limit: int = 50,
    event_type: Optional[EventType] = None,
) -> List[Notification]:
    stmt = (
        select(Notification)
        .options(
            joinedload(Notification.actor),
            joinedload(Notification.inquiry),
        )
        .where(Notification.recipient_admin_id == recipient_admin_id)
    )
    if unread_only:
        stmt = stmt.where(Notification.read_at.is_(None))
    if event_type:
        stmt = stmt.where(Notification.event_type == event_type)

    stmt = stmt.order_by(Notification.created_at.desc()).offset(offset).limit(min(limit, 200))
    return db.execute(stmt).scalars().all()


def unread_count(
    db: Session,
    *,
    recipient_admin_id: int,
    event_type: Optional[EventType] = None,
) -> int:
    return _unread_count(db, recipient_admin_id, event_type=event_type)


def mark_read(
    db: Session,
    *,
    notification_id: int,
    recipient_admin_id: int,
    read_at: Optional[datetime] = None,
) -> bool:
    if read_at is None:
        read_at = datetime.now(timezone.utc)

    res = db.execute(
        update(Notification)
        .where(
            and_(
                Notification.id == notification_id,
                Notification.recipient_admin_id == recipient_admin_id,
                Notification.read_at.is_(None),
            )
        )
        .values(read_at=read_at)
    )

    updated = bool(res.rowcount and res.rowcount > 0)

    if not updated:
        exists = db.execute(
            select(Notification.id).where(
                and_(
                    Notification.id == notification_id,
                    Notification.recipient_admin_id == recipient_admin_id,
                )
            )
        ).scalar_one_or_none()

        if exists is None:
            db.rollback()
            return False

    db.commit()

    ws_manager.publish_sync(
        recipient_admin_id,
        {
            "type": "notification_read",
            "notification_id": notification_id,
            "unread_count": _unread_count(db, recipient_admin_id),
        },
    )
    return True


def mark_all_read(
    db: Session,
    *,
    recipient_admin_id: int,
    event_type: Optional[EventType] = None,
    read_at: Optional[datetime] = None,
) -> int:
    """
    알림 일괄 읽음 처리(옵션).
    - commit 후 WS로 unread_count 동기화 이벤트 전파
    """
    if read_at is None:
        read_at = datetime.now(timezone.utc)

    stmt = (
        update(Notification)
        .where(
            and_(
                Notification.recipient_admin_id == recipient_admin_id,
                Notification.read_at.is_(None),
            )
        )
        .values(read_at=read_at)
    )
    if event_type:
        stmt = stmt.where(Notification.event_type == event_type)

    res = db.execute(stmt)
    db.commit()

    ws_manager.publish_sync(
        recipient_admin_id,
        {
            "type": "unread_count",
            "unread_count": _unread_count(db, recipient_admin_id),
        },
    )

    return int(res.rowcount or 0)
