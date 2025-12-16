# DB 접근 로직

from __future__ import annotations
from typing import Optional, List, Iterable, Literal, Any, Dict, Tuple
from datetime import datetime, timezone
from sqlalchemy import select, update as sa_update, func
from sqlalchemy.orm import Session
from models.chat import ChatSession, Message, Feedback
from fastapi.encoders import jsonable_encoder
Role = Literal["user", "assistant"]
VECTOR_DIM = 1536
# 무응답은 계산하지 않음
## 도움:4 / 미도움:1 / 무응답 : 5 => 문제해결률은 80% (not 40%)
Rating = Literal["helpful", "not_helpful"]

# ---------- helpers ----------
def _safe_extra(extra_data: Any) -> Optional[dict]:
    """
    JSON 컬럼에 안전하게 들어가도록 변환.
    (numpy 타입, datetime, pydantic 객체 등 섞여도 안전)
    """
    if extra_data is None:
        return None
    if isinstance(extra_data, str) and extra_data.lower() == "null":
        return None
    try:
        encoded = jsonable_encoder(extra_data)
        # jsonable_encoder가 list/str 등을 리턴할 수도 있으니 dict로 감싸고 싶으면 여기서 처리
        return encoded if isinstance(encoded, dict) else {"value": encoded}
    except Exception:
        return {"value": str(extra_data)}


# ========== ChatSession ==========
def get_session(db: Session, session_id: int) -> Optional[ChatSession]:
    return db.get(ChatSession, session_id)


def list_sessions(
    db: Session,
    *,
    offset: int = 0,
    limit: int = 50,
    resolved: Optional[bool] = None,
    model_id: Optional[int] = None,
    search: Optional[str] = None,  # title 검색
) -> List[ChatSession]:
    stmt = select(ChatSession).order_by(ChatSession.created_at.desc())
    if resolved is not None:
        stmt = stmt.where(ChatSession.resolved == resolved)
    if model_id is not None:
        stmt = stmt.where(ChatSession.model_id == model_id)
    if search:
        stmt = stmt.where(ChatSession.title.ilike(f"%{search}%"))
    stmt = stmt.offset(offset).limit(min(limit, 100))
    return db.execute(stmt).scalars().all()


def create_session(db: Session, data: Dict[str, Any]) -> ChatSession:
    obj = ChatSession(**data)
    db.add(obj)
    db.commit()
    db.refresh(obj)
    return obj


def update_session(db: Session, session_id: int, data: Dict[str, Any]) -> Optional[ChatSession]:
    obj = get_session(db, session_id)
    if not obj:
        return None
    for key, value in data.items():
        setattr(obj, key, value)
    db.add(obj)
    db.commit()
    db.refresh(obj)
    return obj


def end_session(db: Session, session_id: int, *, resolved: Optional[bool] = None) -> Optional[ChatSession]:
    obj = get_session(db, session_id)
    if not obj:
        return None
    obj.ended_at = datetime.now(timezone.utc)
    if resolved is not None:
        obj.resolved = resolved
    db.add(obj)
    db.commit()
    db.refresh(obj)
    return obj


def delete_session(db: Session, session_id: int) -> bool:
    obj = get_session(db, session_id)
    if not obj:
        return False
    db.delete(obj)  # Message, Feedback는 FK CASCADE/관계에 의해 정리됨
    db.commit()
    return True


# ========== Message ==========
def get_message(db: Session, message_id: int) -> Optional[Message]:
    return db.get(Message, message_id)


def list_messages(
    db: Session,
    session_id: int,
    *,
    offset: int = 0,
    limit: int = 100,
    role: Optional[Role] = None,
) -> List[Message]:
    stmt = (
        select(Message)
        .where(Message.session_id == session_id)
        .order_by(Message.created_at.asc())
        .offset(offset)
        .limit(min(limit, 500))
    )
    if role:
        stmt = stmt.where(Message.role == role)
    return db.execute(stmt).scalars().all()



def create_message(
    db: Session,
    *,
    session_id: int,
    role: Role,
    content: str,
    vector_memory: Optional[List[float]],
    response_latency_ms: Optional[int] = None,
    extra_data: Optional[dict] = None,
) -> Message:
    msg = Message(
        session_id=session_id,
        role=role,
        content=content,
        response_latency_ms=response_latency_ms,
        vector_memory=vector_memory,
        extra_data=jsonable_encoder(extra_data) if extra_data is not None else None,
    )
    db.add(msg)
    try:
        db.commit()
        db.refresh(msg)
        return msg
    except Exception:
        db.rollback()
        raise


def create_assistant_message(
    db: Session,
    *,
    session_id: int,
    content: str,
    response_latency_ms: int,
    extra_data: Optional[Any] = None,
    commit: bool = True,
) -> Message:
    # assistant는 vector_memory=None 고정, latency 필수
    if response_latency_ms is None:
        raise ValueError("response_latency_ms is required for assistant messages")

    return create_message(
        db,
        session_id=session_id,
        role="assistant",
        content=content,
        vector_memory=None,
        response_latency_ms=int(response_latency_ms),
        extra_data=extra_data,
        commit=commit,
    )


def create_user_message(
    db: Session,
    *,
    session_id: int,
    content: str,
    vector_memory: List[float],
    extra_data: Optional[Any] = None,
    commit: bool = True,
) -> Message:
    if vector_memory is None or len(vector_memory) != VECTOR_DIM:
        raise ValueError(f"vector_memory must be length {VECTOR_DIM} for user messages")

    return create_message(
        db,
        session_id=session_id,
        role="user",
        content=content,
        vector_memory=vector_memory,
        response_latency_ms=None,
        extra_data=extra_data,
        commit=commit,
    )

def delete_message(db: Session, message_id: int) -> bool:
    obj = get_message(db, message_id)
    if not obj:
        return False
    db.delete(obj)
    db.commit()
    return True


def last_messages(db: Session, session_id: int, n: int = 1) -> List[Message]:
    stmt = (
        select(Message)
        .where(Message.session_id == session_id)
        .order_by(Message.created_at.desc())
        .limit(max(1, n))
    )
    rows = db.execute(stmt).scalars().all()
    return list(reversed(rows))


def last_by_role(db: Session, session_id: int, role: Role) -> Optional[Message]:
    stmt = (
        select(Message)
        .where(Message.session_id == session_id, Message.role == role)
        .order_by(Message.created_at.desc())
        .limit(1)
    )
    return db.execute(stmt).scalar_one_or_none()


# ========== Feedback ==========
def get_feedback_by_session(db: Session, session_id: int) -> Optional[Feedback]:
    stmt = select(Feedback).where(Feedback.session_id == session_id).limit(1)
    return db.execute(stmt).scalar_one_or_none()


def create_feedback(
    db: Session,
    *,
    rating: Rating,
    session_id: int,
) -> Feedback:
    existing = get_feedback_by_session(db, session_id)
    if existing:
        existing.rating = rating
        db.add(existing)
        db.commit()
        db.refresh(existing)
        return existing

    fb = Feedback(rating=rating, session_id=session_id)
    db.add(fb)
    db.commit()
    db.refresh(fb)
    return fb


def delete_feedback_by_session(db: Session, session_id: int) -> int:
    fb = get_feedback_by_session(db, session_id)
    if not fb:
        return 0
    db.delete(fb)
    db.commit()
    return 1


# ========== 간단 지표 ==========
def session_summary(db: Session, session_id: int) -> Dict[str, Any]:
    total = db.execute(
        select(func.count()).select_from(Message).where(Message.session_id == session_id)
    ).scalar_one()
    users = db.execute(
        select(func.count()).select_from(Message).where(Message.session_id == session_id, Message.role == "user")
    ).scalar_one()
    assistants = total - users
    last = last_messages(db, session_id, 1)
    return {
        "messages_total": int(total or 0),
        "messages_user": int(users or 0),
        "messages_assistant": int(assistants or 0),
        "last_created_at": last[0].created_at if last else None,
    }
