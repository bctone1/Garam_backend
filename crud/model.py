# DB 접근 로직

from __future__ import annotations
from typing import Optional, List, Dict, Any, Literal
from sqlalchemy import select, update as sa_update
from sqlalchemy.orm import Session
from garam_backend.models.model import Model

OrderBy = Literal["recent", "accuracy", "uptime", "speed", "conversations"]


# 단건 조회
def get(db: Session, model_id: int) -> Optional[Model]:
    return db.get(Model, model_id)


def get_active(db: Session) -> Optional[Model]:
    stmt = select(Model).where(Model.is_active.is_(True)).limit(1)
    return db.execute(stmt).scalar_one_or_none()


# 목록
def list_models(
    db: Session,
    *,
    offset: int = 0,
    limit: int = 50,
    provider_name: Optional[str] = None,
    is_active: Optional[bool] = None,
    q: Optional[str] = None,  # name/description 검색
    order_by: OrderBy = "recent",
) -> List[Model]:
    stmt = select(Model)

    if provider_name:
        stmt = stmt.where(Model.provider_name == provider_name)
    if is_active is not None:
        stmt = stmt.where(Model.is_active.is_(is_active))
    if q:
        like = f"%{q}%"
        stmt = stmt.where(Model.name.ilike(like) | Model.description.ilike(like))

    if order_by == "accuracy":
        stmt = stmt.order_by(Model.accuracy.desc(), Model.created_at.desc())
    elif order_by == "uptime":
        stmt = stmt.order_by(Model.uptime_percent.desc(), Model.created_at.desc())
    elif order_by == "speed":
        stmt = stmt.order_by(Model.avg_response_time_ms.asc(), Model.created_at.desc())
    elif order_by == "conversations":
        stmt = stmt.order_by(Model.month_conversations.desc(), Model.created_at.desc())
    else:
        stmt = stmt.order_by(Model.created_at.desc())

    stmt = stmt.offset(offset).limit(min(limit, 100))
    return db.execute(stmt).scalars().all()


# 생성
def create(db: Session, data: Dict[str, Any]) -> Model:
    obj = Model(**data)
    db.add(obj)
    db.commit()
    db.refresh(obj)
    return obj


# 수정
def update(db: Session, model_id: int, data: Dict[str, Any]) -> Optional[Model]:
    obj = get(db, model_id)
    if not obj:
        return None
    for k, v in data.items():
        setattr(obj, k, v)
    db.add(obj)
    db.commit()
    db.refresh(obj)
    return obj


# 삭제
def delete(db: Session, model_id: int) -> bool:
    obj = get(db, model_id)
    if not obj:
        return False
    db.delete(obj)
    db.commit()
    return True


# 활성 전환(부분 유니크 인덱스 대응: 활성은 1개만)
def set_active(db: Session, model_id: int) -> Optional[Model]:
    obj = get(db, model_id)
    if not obj:
        return None
    # 먼저 다른 활성 모두 해제
    db.execute(sa_update(Model).where(Model.is_active.is_(True), Model.id != model_id).values(is_active=False))
    # 대상 활성화
    obj.is_active = True
    db.add(obj)
    db.commit()
    db.refresh(obj)
    return obj


# 비활성화
def deactivate(db: Session, model_id: int) -> Optional[Model]:
    obj = get(db, model_id)
    if not obj:
        return None
    obj.is_active = False
    db.add(obj)
    db.commit()
    db.refresh(obj)
    return obj


# 지표 갱신
def update_metrics(
    db: Session,
    model_id: int,
    *,
    accuracy: Optional[float] = None,
    avg_response_time_ms: Optional[int] = None,
    month_conversations: Optional[int] = None,
    uptime_percent: Optional[float] = None,
    status_text: Optional[str] = None,
) -> Optional[Model]:
    obj = get(db, model_id)
    if not obj:
        return None
    if accuracy is not None:
        obj.accuracy = accuracy
    if avg_response_time_ms is not None:
        obj.avg_response_time_ms = avg_response_time_ms
    if month_conversations is not None:
        obj.month_conversations = month_conversations
    if uptime_percent is not None:
        obj.uptime_percent = uptime_percent
    if status_text is not None:
        obj.status_text = status_text
    db.add(obj)
    db.commit()
    db.refresh(obj)
    return obj
