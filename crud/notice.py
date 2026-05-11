# crud/notice.py
from __future__ import annotations
from typing import Optional, List, Literal, Dict, Any
from datetime import datetime, timezone
from sqlalchemy import select, func, and_, or_
from sqlalchemy.orm import Session
from models.notice import Notice

StatusFilter = Literal["all", "scheduled", "active", "expired"]


def _status_filter_clause(status: StatusFilter):
    now = datetime.now(timezone.utc)
    if status == "scheduled":
        return Notice.start_at > now
    if status == "active":
        return and_(
            or_(Notice.start_at.is_(None), Notice.start_at <= now),
            or_(Notice.end_at.is_(None), Notice.end_at > now),
        )
    if status == "expired":
        return and_(Notice.end_at.isnot(None), Notice.end_at <= now)
    return None


def get(db: Session, notice_id: int) -> Optional[Notice]:
    return db.execute(select(Notice).where(Notice.id == notice_id)).scalars().first()


def list_notices(
    db: Session,
    *,
    offset: int = 0,
    limit: int = 50,
    status: StatusFilter = "all",
    important_only: bool = False,
    q: Optional[str] = None,
) -> List[Notice]:
    stmt = select(Notice)

    clause = _status_filter_clause(status)
    if clause is not None:
        stmt = stmt.where(clause)

    if important_only:
        stmt = stmt.where(Notice.is_important.is_(True))

    if q:
        q = q.strip()
        if q:
            like = f"%{q.lower()}%"
            stmt = stmt.where(
                func.lower(Notice.title).like(like) | func.lower(Notice.content).like(like)
            )

    stmt = stmt.order_by(Notice.is_important.desc(), Notice.created_at.desc())
    stmt = stmt.offset(offset).limit(min(limit, 100))
    return db.execute(stmt).scalars().all()


def count_by_status(db: Session) -> Dict[str, int]:
    now = datetime.now(timezone.utc)
    rows = db.execute(select(Notice)).scalars().all()
    result = {"total": 0, "scheduled": 0, "active": 0, "expired": 0}
    for n in rows:
        result["total"] += 1
        result[n.status] += 1
    return result


def create(db: Session, data: Dict[str, Any]) -> Notice:
    obj = Notice(**data)
    db.add(obj)
    db.commit()
    db.refresh(obj)
    return obj


def update(db: Session, notice_id: int, data: Dict[str, Any]) -> Optional[Notice]:
    obj = db.get(Notice, notice_id)
    if not obj:
        return None
    for k, v in data.items():
        setattr(obj, k, v)
    db.add(obj)
    db.commit()
    db.refresh(obj)
    return obj


def delete(db: Session, notice_id: int) -> bool:
    obj = db.get(Notice, notice_id)
    if not obj:
        return False
    db.delete(obj)
    db.commit()
    return True
