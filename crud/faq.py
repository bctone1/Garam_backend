# DB 접근 로직

from __future__ import annotations
from typing import Optional, List, Literal, Dict, Any
from sqlalchemy import select, func
from sqlalchemy.orm import Session
from models.faq import FAQ

OrderBy = Literal["recent", "views", "satisfaction"]


# 단건 조회
def get(db: Session, faq_id: int) -> Optional[FAQ]:
    return db.get(FAQ, faq_id)


# 목록 조회 + 검색/정렬
def list_faqs(
    db: Session,
    *,
    offset: int = 0,
    limit: int = 50,
    q: Optional[str] = None,                  # question/answer 부분 검색
    order_by: OrderBy = "recent",
) -> List[FAQ]:
    stmt = select(FAQ)

    if q:
        like = f"%{q}%"
        stmt = stmt.where((FAQ.question.ilike(like)) | (FAQ.answer.ilike(like)))

    if order_by == "views":
        stmt = stmt.order_by(FAQ.views.desc(), FAQ.created_at.desc())
    elif order_by == "satisfaction":
        stmt = stmt.order_by(FAQ.satisfaction_rate.desc(), FAQ.created_at.desc())
    else:
        stmt = stmt.order_by(FAQ.created_at.desc())

    stmt = stmt.offset(offset).limit(min(limit, 100))
    return db.execute(stmt).scalars().all()


# 생성
def create(db: Session, data: Dict[str, Any]) -> FAQ:
    obj = FAQ(**data)
    db.add(obj)
    db.commit()
    db.refresh(obj)
    return obj


# 수정
def update(db: Session, faq_id: int, data: Dict[str, Any]) -> Optional[FAQ]:
    obj = get(db, faq_id)
    if not obj:
        return None
    for k, v in data.items():
        setattr(obj, k, v)
    db.add(obj)
    db.commit()
    db.refresh(obj)
    return obj


# 삭제
def delete(db: Session, faq_id: int) -> bool:
    obj = get(db, faq_id)
    if not obj:
        return False
    db.delete(obj)
    db.commit()
    return True


# 조회수 증가
def increment_views(db: Session, faq_id: int, delta: int = 1) -> Optional[FAQ]:
    if delta <= 0:
        delta = 1
    obj = get(db, faq_id)
    if not obj:
        return None
    obj.views = int(obj.views or 0) + delta
    db.add(obj)
    db.commit()
    db.refresh(obj)
    return obj


# 만족도 설정 (0~100)
def set_satisfaction_rate(db: Session, faq_id: int, rate: float) -> Optional[FAQ]:
    if rate < 0:
        rate = 0
    if rate > 100:
        rate = 100
    obj = get(db, faq_id)
    if not obj:
        return None
    obj.satisfaction_rate = rate
    db.add(obj)
    db.commit()
    db.refresh(obj)
    return obj
