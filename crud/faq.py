# crud/faq.py
from __future__ import annotations
from typing import Optional, List, Literal, Dict, Any
from sqlalchemy import select, func
from sqlalchemy.orm import Session, selectinload
from models.faq import FAQ

OrderBy = Literal["recent", "views", "satisfaction"]


def get(db: Session, faq_id: int, *, include_category: bool = False) -> Optional[FAQ]:
    stmt = select(FAQ).where(FAQ.id == faq_id)
    if include_category:
        stmt = stmt.options(selectinload(FAQ.quick_category))
    return db.execute(stmt).scalars().first()


def list_faqs(
    db: Session,
    *,
    offset: int = 0,
    limit: int = 50,
    q: Optional[str] = None,
    order_by: OrderBy = "recent",
    quick_category_id: Optional[int] = None,
    include_category: bool = False,
) -> List[FAQ]:
    stmt = select(FAQ)

    if q:
        q = q.strip()
        if q:
            like = f"%{q.lower()}%"
            stmt = stmt.where(
                func.lower(FAQ.question).like(like) | func.lower(FAQ.answer).like(like)
            )

    if quick_category_id is not None:
        stmt = stmt.where(FAQ.quick_category_id == quick_category_id)

    if order_by == "views":
        stmt = stmt.order_by(FAQ.views.desc(), FAQ.created_at.desc())
    elif order_by == "satisfaction":
        stmt = stmt.order_by(FAQ.satisfaction_rate.desc(), FAQ.created_at.desc())
    else:
        stmt = stmt.order_by(FAQ.created_at.desc())

    if include_category:
        stmt = stmt.options(selectinload(FAQ.quick_category))

    stmt = stmt.offset(offset).limit(min(limit, 100))
    return db.execute(stmt).scalars().all()


def create(db: Session, data: Dict[str, Any]) -> FAQ:
    obj = FAQ(**data)
    db.add(obj)
    db.commit()
    db.refresh(obj)
    return obj


def update(db: Session, faq_id: int, data: Dict[str, Any]) -> Optional[FAQ]:
    obj = db.get(FAQ, faq_id)
    if not obj:
        return None
    for k, v in data.items():
        setattr(obj, k, v)
    db.add(obj)
    db.commit()
    db.refresh(obj)
    return obj


def delete(db: Session, faq_id: int) -> bool:
    obj = db.get(FAQ, faq_id)
    if not obj:
        return False
    db.delete(obj)
    db.commit()
    return True


def increment_views(db: Session, faq_id: int, delta: int = 1) -> Optional[FAQ]:
    if delta <= 0:
        delta = 1
    obj = db.get(FAQ, faq_id)
    if not obj:
        return None
    obj.views = int(obj.views or 0) + delta
    db.add(obj)
    db.commit()
    db.refresh(obj)
    return obj


def set_satisfaction_rate(db: Session, faq_id: int, rate: float) -> Optional[FAQ]:
    rate = 0 if rate < 0 else 100 if rate > 100 else rate
    obj = db.get(FAQ, faq_id)
    if not obj:
        return None
    obj.satisfaction_rate = rate
    db.add(obj)
    db.commit()
    db.refresh(obj)
    return obj
