# DB 접근 로직

from __future__ import annotations
from typing import Optional, List, Dict, Any, Literal
from datetime import datetime, timezone
from sqlalchemy import select, and_
from sqlalchemy.orm import Session
from models.inquiry import Inquiry, InquiryHistory

Status = Literal["new", "processing", "on_hold", "completed"]
Satisfaction = Literal["satisfied", "unsatisfied"]
Action = Literal["assign", "on_hold", "resume", "transfer", "complete", "note", "contact", "delete"]


def serialize_inquiry(inquiry: Inquiry):
    return {
        "id": inquiry.id,
        "name": inquiry.customer_name,
        "company": inquiry.company,
        "phone": inquiry.phone,
        "content": inquiry.content,
        "status": inquiry.status,
        "createdDate": inquiry.created_at.strftime("%Y-%m-%d %H:%M") if inquiry.created_at else None,
        "assignee": inquiry.assignee.name if inquiry.assignee else None,
        "assignedDate": inquiry.assigned_at.strftime("%Y-%m-%d %H:%M") if inquiry.assigned_at else None,
        "completedDate": inquiry.completed_at.strftime("%Y-%m-%d %H:%M") if inquiry.completed_at else None,
        "history": [
            {
                "action": h.action,
                "admin": h.admin_name,
                "timestamp": h.created_at.strftime("%Y-%m-%d %H:%M") if h.created_at else None,
                "details": h.details
            }
            for h in inquiry.histories
        ]
    }




# ====== Inquiry ======
def get(db: Session, inquiry_id: int) -> Optional[Inquiry]:
    return db.get(Inquiry, inquiry_id)


def list_inquiries(
        db: Session,
        *,
        offset: int = 0,
        limit: int = 50,
        status: Optional[Status] = None,
        assignee_admin_id: Optional[int] = None,
        q: Optional[str] = None,  # customer_name/company/phone/content 검색
        created_from: Optional[datetime] = None,
        created_to: Optional[datetime] = None,
) -> List[Inquiry]:
    stmt = select(Inquiry)

    conds = []
    if status:
        conds.append(Inquiry.status == status)
    if assignee_admin_id is not None:
        conds.append(Inquiry.assignee_admin_id == assignee_admin_id)
    if created_from:
        conds.append(Inquiry.created_at >= created_from)
    if created_to:
        conds.append(Inquiry.created_at < created_to)
    if q:
        like = f"%{q}%"
        conds.append(
            (Inquiry.customer_name.ilike(like))
            | (Inquiry.company.ilike(like))
            | (Inquiry.phone.ilike(like))
            | (Inquiry.content.ilike(like))
        )
    if conds:
        stmt = stmt.where(and_(*conds))

    stmt = stmt.order_by(Inquiry.created_at.desc()).offset(offset).limit(min(limit, 100))
    return db.execute(stmt).scalars().all()


def create(db: Session, data: dict) -> Inquiry:
    # 방어: 0, "", "0" → NULL
    if data.get("assignee_admin_id") in (0, "0", ""):
        data["assignee_admin_id"] = None
    if data.get("customer_satisfaction") in ("", "null", "None"):
        data["customer_satisfaction"] = None
    # 일관성: 둘 다 NULL 또는 둘 다 NOT NULL
    if (data.get("assignee_admin_id") is None) != (data.get("assigned_at") is None):
        data["assignee_admin_id"] = None
        data["assigned_at"] = None

    obj = Inquiry(**data)
    db.add(obj)
    db.commit()
    db.refresh(obj)
    return obj


def update(db: Session, inquiry_id: int, data: Dict[str, Any]) -> Optional[Inquiry]:
    obj = get(db, inquiry_id)
    if not obj:
        return None

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


# ====== Workflow helpers (제약 일치 보조) ======
def assign(
        db: Session, inquiry_id: int, admin_id: int, *, actor_admin_id: Optional[int] = None
) -> Optional[Inquiry]:
    obj = get(db, inquiry_id)
    if not obj:
        return None
    obj.assignee_admin_id = admin_id
    obj.assigned_at = datetime.now(timezone.utc)
    obj.status = "processing"
    db.add(obj)
    _add_history(db, inquiry_id, action="assign", admin_id=actor_admin_id, to_admin_id=admin_id)
    db.commit()
    db.refresh(obj)
    return obj


def unassign(db: Session, inquiry_id: int, *, actor_admin_id: Optional[int] = None) -> Optional[Inquiry]:
    obj = get(db, inquiry_id)
    if not obj:
        return None
    obj.assignee_admin_id = None
    obj.assigned_at = None
    # 상태는 유지. 필요시 on_hold로 전환 원하면 set_status 사용.
    db.add(obj)
    _add_history(db, inquiry_id, action="note", admin_id=actor_admin_id, details="unassign")
    db.commit()
    db.refresh(obj)
    return obj


def transfer(
        db: Session, inquiry_id: int, to_admin_id: int, *, actor_admin_id: Optional[int] = None
) -> Optional[Inquiry]:
    obj = get(db, inquiry_id)
    if not obj:
        return None
    obj.assignee_admin_id = to_admin_id
    obj.assigned_at = datetime.now(timezone.utc)
    db.add(obj)
    _add_history(db, inquiry_id, action="transfer", admin_id=actor_admin_id, to_admin_id=to_admin_id)
    db.commit()
    db.refresh(obj)
    return obj


def set_status(
        db: Session, inquiry_id: int, status: Status, *, actor_admin_id: Optional[int] = None,
        details: Optional[str] = None
) -> Optional[Inquiry]:
    obj = get(db, inquiry_id)
    if not obj:
        return None
    obj.status = status
    if status == "completed" and obj.completed_at is None:
        obj.completed_at = datetime.now(timezone.utc)
    db.add(obj)
    _add_history(db, inquiry_id, action=("complete" if status == "completed" else "note"),
                 admin_id=actor_admin_id, details=details or f"status={status}")
    db.commit()
    db.refresh(obj)
    return obj


def set_customer_satisfaction(
        db: Session, inquiry_id: int, satisfaction: Satisfaction
) -> Optional[Inquiry]:
    obj = get(db, inquiry_id)
    if not obj:
        return None
    obj.customer_satisfaction = satisfaction
    db.add(obj)
    db.commit()
    db.refresh(obj)
    return obj


# ====== InquiryHistory ======
def _add_history(
        db: Session,
        inquiry_id: int,
        *,
        action: Action,
        admin_id: Optional[int] = None,
        to_admin_id: Optional[int] = None,
        details: Optional[str] = None,
) -> InquiryHistory:
    hist = InquiryHistory(
        inquiry_id=inquiry_id,
        action=action,
        admin_id=admin_id,
        to_admin_id=to_admin_id,
        details=details,
    )
    db.add(hist)
    # commit은 호출자에서 한번에 수행하는 것을 기본으로 한다.
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
        db: Session, inquiry_id: int, *, admin_id: Optional[int], details: Optional[str]
) -> InquiryHistory:
    hist = _add_history(db, inquiry_id, action="note", admin_id=admin_id, details=details)
    db.commit()
    db.refresh(hist)
    return hist
