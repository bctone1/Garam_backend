# CRUD/model.py
from typing import Optional, Dict, Any
from sqlalchemy import select
from sqlalchemy.orm import Session
from models.model import Model

SINGLE_ID = 1

def get_single(db: Session) -> Optional[Model]:
    stmt = select(Model).where(Model.id == SINGLE_ID)
    return db.execute(stmt).scalar_one_or_none()

def update_single(db: Session, data: Dict[str, Any]) -> Optional[Model]:
    obj = get_single(db)
    if not obj:
        # 최초 1행이 아예 없다면 생성
        obj = Model(id=SINGLE_ID, **data)
        db.add(obj)
    else:
        for key, value in data.items():
            setattr(obj, key, value)
        db.add(obj)
    db.commit()
    db.refresh(obj)
    return obj

def update_metrics(
    db: Session,
    *,
    accuracy: Optional[float] = None,
    avg_response_time_ms: Optional[int] = None,
    month_conversations: Optional[int] = None,
    uptime_percent: Optional[float] = None,
) -> Optional[Model]:
    obj = get_single(db)
    if not obj:
        return None
    if accuracy is not None: obj.accuracy = accuracy
    if avg_response_time_ms is not None: obj.avg_response_time_ms = avg_response_time_ms
    if month_conversations is not None: obj.month_conversations = month_conversations
    if uptime_percent is not None: obj.uptime_percent = uptime_percent
    db.add(obj); db.commit(); db.refresh(obj)
    return obj
