# crud/inquiry.py
from __future__ import annotations

import os
import re
import shutil
from uuid import uuid4
from typing import Optional, List, Dict, Any, Literal
from datetime import datetime, timezone

from sqlalchemy import select, and_, func
from sqlalchemy.orm import Session

import core.config as config
from models.inquiry import Inquiry, InquiryHistory, InquiryAttachment, Notification
from models.admin_user import AdminUser  # 이름 해석용
from service.ws_manager import ws_manager

try:
    from fastapi import UploadFile  # optional (멀티파트 업로드 시 사용)
except Exception:  # pragma: no cover
    UploadFile = Any  # type: ignore


Status = Literal["new", "processing", "on_hold", "completed"]
Satisfaction = Literal["satisfied", "unsatisfied"]
InquiryType = Literal["paper_request", "sales_report", "kiosk_menu_update", "other"]

Action = Literal["new", "assign", "on_hold", "resume", "transfer", "complete", "note", "contact", "delete"]

StorageType = Literal["local", "s3"]

NotificationEvent = Literal["inquiry_new", "inquiry_assigned", "inquiry_completed"]

_ALLOWED_INQUIRY_TYPES = {"paper_request", "sales_report", "kiosk_menu_update", "other"}
_ALLOWED_STORAGE_TYPES = {"local", "s3"}

MAX_ATTACHMENTS = 3
REP_ADMIN_ID = 0


# ======================
# Utils
# ======================
def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _resolve_admin_name(db: Session, admin_id: Optional[int]) -> Optional[str]:
    if admin_id is None:
        return None
    row = db.get(AdminUser, admin_id)
    return row.name if row else None


def _normalize_inquiry_type(v: Any) -> str:
    if v in (None, "", "0", 0, "null", "None"):
        return "other"
    s = str(v).strip()
    if s not in _ALLOWED_INQUIRY_TYPES:
        raise ValueError(f"invalid inquiry_type: {s}")
    return s


def _normalize_storage_type(v: Any) -> str:
    if v in (None, "", "null", "None"):
        return "local"
    s = str(v).strip().lower()
    if s not in _ALLOWED_STORAGE_TYPES:
        raise ValueError(f"invalid storage_type: {s}")
    return s


def _safe_filename(name: str) -> str:
    name = (name or "upload").strip()
    name = name.replace("\\", "_").replace("/", "_")
    name = re.sub(r"[^0-9A-Za-z._\-가-힣 ]+", "_", name)
    name = re.sub(r"\s+", "_", name).strip("_")
    return name or "upload"


def serialize_inquiry(inquiry: Inquiry):
    return {
        "id": inquiry.id,
        "businessName": inquiry.business_name,
        "businessNumber": inquiry.business_number,
        "phone": inquiry.phone,
        "content": inquiry.content,
        "status": inquiry.status,
        "inquiryType": getattr(inquiry, "inquiry_type", "other"),
        "createdDate": inquiry.created_at.strftime("%Y-%m-%d %H:%M") if inquiry.created_at else None,
        "assignee": inquiry.assignee.name if inquiry.assignee else None,
        "assignedDate": inquiry.assigned_at.strftime("%Y-%m-%d %H:%M") if inquiry.assigned_at else None,
        "completedDate": inquiry.completed_at.strftime("%Y-%m-%d %H:%M") if inquiry.completed_at else None,
        "attachments": [
            {
                "id": a.id,
                "storageType": getattr(a, "storage_type", "local"),
                "storageKey": a.storage_key,
                "originalName": a.original_name,
                "contentType": a.content_type,
                "sizeBytes": a.size_bytes,
                "createdAt": a.created_at.strftime("%Y-%m-%d %H:%M") if a.created_at else None,
            }
            for a in getattr(inquiry, "attachments", []) or []
        ],
        "history": [
            {
                "id": h.id,
                "action": h.action,
                "admin": h.admin_name,
                "timestamp": h.created_at.strftime("%Y-%m-%d %H:%M") if h.created_at else None,
                "details": h.details,
            }
            for h in inquiry.histories
        ],
    }


# ======================
# WS payload helpers
# ======================
def _unread_count(db: Session, recipient_admin_id: int) -> int:
    return int(
        db.execute(
            select(func.count())
            .select_from(Notification)
            .where(
                and_(
                    Notification.recipient_admin_id == recipient_admin_id,
                    Notification.read_at.is_(None),
                )
            )
        ).scalar_one()
        or 0
    )


def _build_notification_message(
    *,
    event_type: str,
    business_name: Optional[str],
    actor_name: Optional[str],
) -> tuple[str, str]:
    bn = business_name or "해당 업체"
    actor = actor_name or "관리자"

    if event_type == "inquiry_new":
        return "새 문의 접수", f"{bn}에서 문의가 접수됐습니다."
    if event_type == "inquiry_assigned":
        return "문의 할당", f"{actor}가 {bn} 문의가  할당됐습니다."
    if event_type == "inquiry_completed":
        return "문의 완료", f"{actor}가 {bn} 문의를 완료 처리했습니다."
    return "알림", f"{bn} 관련 알림 도착."


def _publish_notification_created_sync(
    db: Session,
    *,
    recipient_admin_id: int,
    notification_id: int,
    inquiry_id: int,
    event_type: NotificationEvent,
    actor_admin_id: Optional[int],
    actor_name: Optional[str],
    business_name: Optional[str],
    created_at: Optional[datetime],
) -> None:
    title, body = _build_notification_message(
        event_type=event_type,
        business_name=business_name,
        actor_name=actor_name,
    )

    payload = {
        "type": "notification_created",
        "notification": {
            "id": notification_id,
            "recipient_admin_id": recipient_admin_id,
            "event_type": event_type,
            "inquiry_id": inquiry_id,
            "actor_admin_id": actor_admin_id,
            "created_at": (created_at or _utcnow()).isoformat(),
            "read_at": None,
            "title": title,
            "body": body,
            "deep_link": f"/inquiries/{inquiry_id}",
        },
        "unread_count": _unread_count(db, recipient_admin_id),
    }

    # sync endpoint/threadpool에서도 안전
    ws_manager.publish_sync(recipient_admin_id, payload)


# ======================
# Attachment helpers
# ======================
def _validate_and_normalize_attachments(attachments: Any) -> List[Dict[str, Any]]:
    if not attachments:
        return []
    if not isinstance(attachments, list):
        raise ValueError("attachments must be a list")
    if len(attachments) > MAX_ATTACHMENTS:
        raise ValueError(f"attachments max {MAX_ATTACHMENTS}")

    out: List[Dict[str, Any]] = []
    for a in attachments:
        if not isinstance(a, dict):
            raise ValueError("attachment item must be an object")

        storage_key = (a.get("storage_key") or a.get("storageKey") or "").strip()
        if not storage_key:
            raise ValueError("attachment.storage_key is required")

        out.append(
            {
                "storage_type": _normalize_storage_type(a.get("storage_type") or a.get("storageType") or "local"),
                "storage_key": storage_key,
                "original_name": a.get("original_name") or a.get("originalName"),
                "content_type": a.get("content_type") or a.get("contentType"),
                "size_bytes": a.get("size_bytes") or a.get("sizeBytes"),
            }
        )
    return out


def save_inquiry_files_local(
    *,
    inquiry_id: int,
    files: List[UploadFile],
) -> List[Dict[str, Any]]:
    """
    멀티파트로 받은 파일을 로컬 저장하고,
    add_attachments(db, inquiry_id, saved_meta)로 넣을 수 있는 dict 리스트를 리턴.
    """
    if len(files) > MAX_ATTACHMENTS:
        raise ValueError(f"attachments max {MAX_ATTACHMENTS}")

    base_dir = getattr(config, "UPLOAD_FOLDER", "uploads")
    attach_dir = os.path.join(base_dir, "inquiry", str(inquiry_id), "attachments")
    os.makedirs(attach_dir, exist_ok=True)

    saved: List[Dict[str, Any]] = []
    for f in files:
        origin = _safe_filename(getattr(f, "filename", None) or "upload")
        fname = f"{inquiry_id}_{uuid4().hex[:8]}_{origin}"
        fpath = os.path.join(attach_dir, fname)

        f.file.seek(0)
        with open(fpath, "wb") as out:
            shutil.copyfileobj(f.file, out, length=1024 * 1024)

        size_bytes = os.path.getsize(fpath)
        saved.append(
            {
                "storage_type": "local",
                "storage_key": fpath,
                "original_name": origin,
                "content_type": getattr(f, "content_type", None),
                "size_bytes": size_bytes,
            }
        )
    return saved


def add_attachments(
    db: Session,
    inquiry_id: int,
    attachments: List[Dict[str, Any]],
) -> List[InquiryAttachment]:
    """
    기존 첨부 포함해서 최대 3장 제한.
    """
    normalized = _validate_and_normalize_attachments(attachments)

    existing_cnt = db.execute(
        select(func.count()).select_from(InquiryAttachment).where(InquiryAttachment.inquiry_id == inquiry_id)
    ).scalar_one()

    if existing_cnt + len(normalized) > MAX_ATTACHMENTS:
        raise ValueError(f"attachments max {MAX_ATTACHMENTS}")

    objs: List[InquiryAttachment] = []
    for a in normalized:
        objs.append(
            InquiryAttachment(
                inquiry_id=inquiry_id,
                storage_type=a["storage_type"],
                storage_key=a["storage_key"],
                original_name=a.get("original_name"),
                content_type=a.get("content_type"),
                size_bytes=a.get("size_bytes"),
            )
        )

    db.add_all(objs)
    return objs


# ======================
# Notification helper (DB insert only)
# ======================
def _add_notification(
    db: Session,
    *,
    recipient_admin_id: int,
    event_type: NotificationEvent,
    inquiry_id: int,
    actor_admin_id: Optional[int] = None,
) -> Notification:
    n = Notification(
        recipient_admin_id=recipient_admin_id,
        event_type=event_type,
        inquiry_id=inquiry_id,
        actor_admin_id=actor_admin_id,
    )
    db.add(n)
    return n


# ======================
# Inquiry
# ======================
def get(db: Session, inquiry_id: int) -> Optional[Inquiry]:
    return db.get(Inquiry, inquiry_id)


def list_inquiries(
    db: Session,
    *,
    offset: int = 0,
    limit: int = 50,
    status: Optional[Status] = None,
    inquiry_type: Optional[InquiryType] = None,
    assignee_admin_id: Optional[int] = None,
    q: Optional[str] = None,
    created_from: Optional[datetime] = None,
    created_to: Optional[datetime] = None,
) -> List[Inquiry]:
    stmt = select(Inquiry)
    conds = []

    if status:
        conds.append(Inquiry.status == status)
    if inquiry_type:
        conds.append(Inquiry.inquiry_type == inquiry_type)
    if assignee_admin_id is not None:
        conds.append(Inquiry.assignee_admin_id == assignee_admin_id)
    if created_from:
        conds.append(Inquiry.created_at >= created_from)
    if created_to:
        conds.append(Inquiry.created_at < created_to)

    if q:
        like = f"%{q}%"
        conds.append(
            (Inquiry.business_name.ilike(like))
            | (Inquiry.business_number.ilike(like))
            | (Inquiry.phone.ilike(like))
            | (Inquiry.content.ilike(like))
        )

    if conds:
        stmt = stmt.where(and_(*conds))

    stmt = stmt.order_by(Inquiry.created_at.desc()).offset(offset).limit(min(limit, 100))
    return db.execute(stmt).scalars().all()


def create(db: Session, data: dict) -> Inquiry:
    attachments_payload = data.pop("attachments", None)
    attachments = _validate_and_normalize_attachments(attachments_payload)

    # 정규화
    if data.get("assignee_admin_id") in (0, "0", ""):
        data["assignee_admin_id"] = None
    if data.get("customer_satisfaction") in ("", "null", "None"):
        data["customer_satisfaction"] = None

    data["inquiry_type"] = _normalize_inquiry_type(data.get("inquiry_type"))

    # assignee/assigned_at 일관성
    if (data.get("assignee_admin_id") is None) != (data.get("assigned_at") is None):
        data["assignee_admin_id"] = None
        data["assigned_at"] = None

    # 사전 할당 생성(드물겠지만) 방어: assignee 있으면 assigned_by 필수
    if data.get("assignee_admin_id") is not None:
        data.setdefault("assigned_at", _utcnow())
        data.setdefault("status", "processing")
        data.setdefault("assigned_by_admin_id", REP_ADMIN_ID)
        if data.get("assigned_by_admin_id") == REP_ADMIN_ID:
            data.setdefault("delegated_from_admin_id", REP_ADMIN_ID)

    # completed로 생성하는 케이스 방어
    if data.get("status") == "completed":
        data.setdefault("completed_at", _utcnow())
        data.setdefault("completed_by_admin_id", data.get("assignee_admin_id") or REP_ADMIN_ID)

    obj = Inquiry(**data)
    db.add(obj)
    db.flush()

    db.add(
        InquiryHistory(
            inquiry_id=obj.id,
            action="new",
            admin_name="시스템",
            details="챗봇을 통해 문의가 접수되었습니다.",
        )
    )

    # 새 문의 알림(DB)
    notif = _add_notification(
        db,
        recipient_admin_id=REP_ADMIN_ID,
        event_type="inquiry_new",
        inquiry_id=obj.id,
        actor_admin_id=None,
    )
    db.flush()  # notif.id 확보

    if attachments:
        add_attachments(db, obj.id, attachments)

    db.commit()
    db.refresh(obj)

    # WS publish (after commit)
    _publish_notification_created_sync(
        db,
        recipient_admin_id=REP_ADMIN_ID,
        notification_id=notif.id,
        inquiry_id=obj.id,
        event_type="inquiry_new",
        actor_admin_id=None,
        actor_name=None,
        business_name=obj.business_name,
        created_at=getattr(notif, "created_at", None),
    )

    return obj


def update(db: Session, inquiry_id: int, data: Dict[str, Any]) -> Optional[Inquiry]:
    """
    일반 업데이트(알림/워크플로우 이벤트는 assign/transfer/set_status로 처리 권장)
    """
    obj = get(db, inquiry_id)
    if not obj:
        return None

    # 첨부 추가 허용 시 max3 적용
    if "attachments" in data:
        attachments_payload = data.pop("attachments", None)
        if attachments_payload:
            add_attachments(db, inquiry_id, attachments_payload)

    if "inquiry_type" in data:
        data["inquiry_type"] = _normalize_inquiry_type(data.get("inquiry_type"))

    # assignee/assigned_at 일관성 보조
    if ("assignee_admin_id" in data) ^ ("assigned_at" in data):
        data.setdefault("assignee_admin_id", None)
        data.setdefault("assigned_at", None)

    # 제약 대응(안전장치)
    if data.get("assignee_admin_id") is not None:
        data.setdefault("assigned_by_admin_id", obj.assigned_by_admin_id or REP_ADMIN_ID)
        if data.get("assigned_by_admin_id") == REP_ADMIN_ID and obj.delegated_from_admin_id is None:
            data.setdefault("delegated_from_admin_id", REP_ADMIN_ID)

    if data.get("assignee_admin_id") is None and "assignee_admin_id" in data:
        data.setdefault("assigned_at", None)
        data.setdefault("assigned_by_admin_id", None)

    if data.get("status") == "completed":
        if obj.completed_at is None and not data.get("completed_at"):
            data["completed_at"] = _utcnow()
        if not data.get("completed_by_admin_id") and obj.completed_by_admin_id is None:
            data["completed_by_admin_id"] = obj.assignee_admin_id or REP_ADMIN_ID

    for k, v in data.items():
        setattr(obj, k, v)

    db.add(obj)
    db.commit()
    db.refresh(obj)
    return obj


def delete(db: Session, inquiry_id: int) -> bool:
    obj = get(db, inquiry_id)
    if not obj:
        return False
    db.delete(obj)
    db.commit()
    return True


# ======================
# Workflow helpers (알림 생성 + WS publish)
# ======================
def assign(db: Session, inquiry_id: int, admin_id: int, *, actor_admin_id: Optional[int] = None) -> Optional[Inquiry]:
    obj = get(db, inquiry_id)
    if not obj:
        return None

    actor_id = actor_admin_id if actor_admin_id is not None else REP_ADMIN_ID
    actor_name = _resolve_admin_name(db, actor_id)

    obj.assignee_admin_id = admin_id
    obj.assigned_at = _utcnow()
    obj.status = "processing"

    obj.assigned_by_admin_id = actor_id
    if actor_id == REP_ADMIN_ID and obj.delegated_from_admin_id is None:
        obj.delegated_from_admin_id = REP_ADMIN_ID

    _add_history(
        db,
        inquiry_id,
        action="assign",
        admin_name=actor_name,
        details=f"assignee_admin_id={admin_id}",
    )

    notif = _add_notification(
        db,
        recipient_admin_id=admin_id,
        event_type="inquiry_assigned",
        inquiry_id=inquiry_id,
        actor_admin_id=actor_id,
    )
    db.flush()

    db.add(obj)
    db.commit()
    db.refresh(obj)

    _publish_notification_created_sync(
        db,
        recipient_admin_id=admin_id,
        notification_id=notif.id,
        inquiry_id=inquiry_id,
        event_type="inquiry_assigned",
        actor_admin_id=actor_id,
        actor_name=actor_name,
        business_name=obj.business_name,
        created_at=getattr(notif, "created_at", None),
    )

    return obj


def unassign(db: Session, inquiry_id: int, *, actor_admin_id: Optional[int] = None) -> Optional[Inquiry]:
    obj = get(db, inquiry_id)
    if not obj:
        return None

    obj.assignee_admin_id = None
    obj.assigned_at = None
    obj.assigned_by_admin_id = None

    db.add(obj)
    _add_history(
        db,
        inquiry_id,
        action="note",
        admin_name=_resolve_admin_name(db, actor_admin_id),
        details="unassign",
    )
    db.commit()
    db.refresh(obj)
    return obj


def transfer(
    db: Session, inquiry_id: int, to_admin_id: int, *, actor_admin_id: Optional[int] = None
) -> Optional[Inquiry]:
    obj = get(db, inquiry_id)
    if not obj:
        return None

    actor_id = actor_admin_id if actor_admin_id is not None else REP_ADMIN_ID
    actor_name = _resolve_admin_name(db, actor_id)

    obj.assignee_admin_id = to_admin_id
    obj.assigned_at = _utcnow()
    obj.status = "processing"

    obj.assigned_by_admin_id = actor_id
    if actor_id == REP_ADMIN_ID and obj.delegated_from_admin_id is None:
        obj.delegated_from_admin_id = REP_ADMIN_ID

    _add_history(
        db,
        inquiry_id,
        action="transfer",
        admin_name=actor_name,
        details=f"to_admin_id={to_admin_id}",
    )

    notif = _add_notification(
        db,
        recipient_admin_id=to_admin_id,
        event_type="inquiry_assigned",
        inquiry_id=inquiry_id,
        actor_admin_id=actor_id,
    )
    db.flush()

    db.add(obj)
    db.commit()
    db.refresh(obj)

    _publish_notification_created_sync(
        db,
        recipient_admin_id=to_admin_id,
        notification_id=notif.id,
        inquiry_id=inquiry_id,
        event_type="inquiry_assigned",
        actor_admin_id=actor_id,
        actor_name=actor_name,
        business_name=obj.business_name,
        created_at=getattr(notif, "created_at", None),
    )

    return obj


def set_status(
    db: Session,
    inquiry_id: int,
    status: Status,
    *,
    actor_admin_id: Optional[int] = None,
    details: Optional[str] = None,
) -> Optional[Inquiry]:
    obj = get(db, inquiry_id)
    if not obj:
        return None

    obj.status = status

    if status == "completed":
        actor_id = actor_admin_id if actor_admin_id is not None else (obj.assignee_admin_id or REP_ADMIN_ID)
        actor_name = _resolve_admin_name(db, actor_id)

        if obj.completed_at is None:
            obj.completed_at = _utcnow()

        obj.completed_by_admin_id = actor_id

        _add_history(
            db,
            inquiry_id,
            action="complete",
            admin_name=actor_name,
            details=details or "completed",
        )

        notif = _add_notification(
            db,
            recipient_admin_id=REP_ADMIN_ID,
            event_type="inquiry_completed",
            inquiry_id=inquiry_id,
            actor_admin_id=actor_id,
        )
        db.flush()

        db.add(obj)
        db.commit()
        db.refresh(obj)

        _publish_notification_created_sync(
            db,
            recipient_admin_id=REP_ADMIN_ID,
            notification_id=notif.id,
            inquiry_id=inquiry_id,
            event_type="inquiry_completed",
            actor_admin_id=actor_id,
            actor_name=actor_name,
            business_name=obj.business_name,
            created_at=getattr(notif, "created_at", None),
        )
        return obj

    elif status == "on_hold":
        _add_history(
            db,
            inquiry_id,
            action="on_hold",
            admin_name=_resolve_admin_name(db, actor_admin_id),
            details=details or "on_hold",
        )
    elif status == "processing":
        _add_history(
            db,
            inquiry_id,
            action="resume",
            admin_name=_resolve_admin_name(db, actor_admin_id),
            details=details or "processing",
        )
    else:
        if details:
            _add_history(
                db,
                inquiry_id,
                action="note",
                admin_name=_resolve_admin_name(db, actor_admin_id),
                details=details,
            )

    db.add(obj)
    db.commit()
    db.refresh(obj)
    return obj


def set_customer_satisfaction(db: Session, inquiry_id: int, satisfaction: Satisfaction) -> Optional[Inquiry]:
    obj = get(db, inquiry_id)
    if not obj:
        return None
    obj.customer_satisfaction = satisfaction
    db.add(obj)
    db.commit()
    db.refresh(obj)
    return obj


# ======================
# InquiryHistory
# ======================
def _add_history(
    db: Session,
    inquiry_id: int,
    *,
    action: str,
    admin_name: Optional[str] = None,
    details: Optional[str] = None,
) -> InquiryHistory:
    hist = InquiryHistory(
        inquiry_id=inquiry_id,
        action=action,
        admin_name=admin_name,
        details=details,
    )
    db.add(hist)
    return hist


def list_histories(db: Session, inquiry_id: int, *, offset: int = 0, limit: int = 100) -> List[InquiryHistory]:
    stmt = (
        select(InquiryHistory)
        .where(InquiryHistory.inquiry_id == inquiry_id)
        .order_by(InquiryHistory.created_at.asc())
        .offset(offset)
        .limit(min(limit, 500))
    )
    return db.execute(stmt).scalars().all()


def add_history_note(
    db: Session,
    inquiry_id: int,
    action: str,
    *,
    admin_id: Optional[int],
    details: Optional[str],
) -> InquiryHistory:
    hist = _add_history(
        db,
        inquiry_id,
        action=action,
        admin_name=_resolve_admin_name(db, admin_id),
        details=details,
    )
    db.commit()
    db.refresh(hist)
    return hist
