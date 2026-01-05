# crud/chat.py
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, List, Literal, Optional

from fastapi.encoders import jsonable_encoder
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from models.chat import ChatSession, Message, Feedback

Role = Literal["user", "assistant"]
Rating = Literal["helpful", "not_helpful"]

VECTOR_DIM = 1536  # pgvector(1536)


# =========================================================
# helpers
# =========================================================
def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _safe_json(v: Any) -> Any:
    """
    JSON/JSONB 컬럼에 안전하게 들어가도록 변환.
    - pydantic/ORM/datetime/numpy 등이 섞여도 저장 가능하도록 처리
    """
    if v is None:
        return None
    if isinstance(v, str) and v.lower() == "null":
        return None
    try:
        return jsonable_encoder(v)
    except Exception:
        return str(v)


def _validate_vector(vec: Optional[List[float]]) -> Optional[List[float]]:
    if vec is None:
        return None
    if len(vec) != VECTOR_DIM:
        raise ValueError(f"vector_memory must be length {VECTOR_DIM}")
    return vec


# =========================================================
# ChatSession
# =========================================================
def get_session(db: Session, session_id: int) -> Optional[ChatSession]:
    return db.get(ChatSession, session_id)


def list_sessions(
    db: Session,
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
    return list(db.scalars(stmt).all())


def create_session(db: Session, data: Dict[str, Any], commit: bool = True) -> ChatSession:
    obj = ChatSession(**data)
    db.add(obj)
    if commit:
        db.commit()
        db.refresh(obj)
    else:
        db.flush()
    return obj


def update_session(db: Session, session_id: int, data: Dict[str, Any], commit: bool = True) -> Optional[ChatSession]:
    obj = get_session(db, session_id)
    if not obj:
        return None
    for key, value in data.items():
        setattr(obj, key, value)
    db.add(obj)
    if commit:
        db.commit()
        db.refresh(obj)
    else:
        db.flush()
    return obj


def end_session(db: Session, session_id: int, resolved: Optional[bool] = None, commit: bool = True) -> Optional[ChatSession]:
    obj = get_session(db, session_id)
    if not obj:
        return None
    obj.ended_at = _utcnow()
    if resolved is not None:
        obj.resolved = resolved
    db.add(obj)
    if commit:
        db.commit()
        db.refresh(obj)
    else:
        db.flush()
    return obj


def delete_session(db: Session, session_id: int, commit: bool = True) -> bool:
    obj = get_session(db, session_id)
    if not obj:
        return False
    db.delete(obj)
    if commit:
        db.commit()
    else:
        db.flush()
    return True


# =========================================================
# Message
# =========================================================
def get_message(db: Session, message_id: int) -> Optional[Message]:
    return db.get(Message, message_id)


def list_messages(
    db: Session,
    session_id: int,
    offset: int = 0,
    limit: int = 200,
    role: Optional[Role] = None,
) -> List[Message]:
    """
    레거시 호환: runner/endpoint에서 positional로 호출하는 경우가 있어
    키워드 전용(*)을 쓰지 않음.
    """
    stmt = (
        select(Message)
        .where(Message.session_id == session_id)
        .order_by(Message.created_at.asc())
        .offset(offset)
        .limit(min(limit, 500))
    )
    if role:
        stmt = stmt.where(Message.role == role)
    return list(db.scalars(stmt).all())


def create_message(
    db: Session,
    session_id: int,
    role: Role,
    content: str,
    vector_memory: Optional[List[float]] = None,
    response_latency_ms: Optional[int] = None,
    extra_data: Optional[Any] = None,
    commit: bool = True,
    refresh: bool = True,
) -> Message:
    """
    레거시 호환:
    - 일부 코드가 create_message(..., commit=...) 형태로 호출함
    - 일부는 positional/keyword 혼용 가능
    """
    msg = Message(
        session_id=session_id,
        role=role,
        content=content,
        response_latency_ms=response_latency_ms,
        vector_memory=_validate_vector(vector_memory),
        extra_data=_safe_json(extra_data),
    )
    db.add(msg)
    try:
        if commit:
            db.commit()
            if refresh:
                db.refresh(msg)
        else:
            db.flush()
            if refresh:
                db.refresh(msg)
        return msg
    except Exception:
        db.rollback()
        raise


def create_user_message(
    db: Session,
    session_id: int,
    content: str,
    vector_memory: List[float],
    extra_data: Optional[Any] = None,
    commit: bool = True,
) -> Message:
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


def create_assistant_message(
    db: Session,
    session_id: int,
    content: str,
    response_latency_ms: int,
    extra_data: Optional[Any] = None,
    commit: bool = True,
) -> Message:
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


def delete_message(db: Session, message_id: int, commit: bool = True) -> bool:
    obj = get_message(db, message_id)
    if not obj:
        return False
    db.delete(obj)
    if commit:
        db.commit()
    else:
        db.flush()
    return True


def last_messages(db: Session, session_id: int, n: int = 1) -> List[Message]:
    """
    레거시 호환: positional 호출 유지
    """
    stmt = (
        select(Message)
        .where(Message.session_id == session_id)
        .order_by(Message.created_at.desc())
        .limit(max(1, n))
    )
    rows = list(db.scalars(stmt).all())
    rows.reverse()
    return rows


def last_by_role(db: Session, session_id: int, role: Role) -> Optional[Message]:
    """
    레거시 호환: runner가 last_by_role(db, session_id, "user") 형태로 호출
    """
    stmt = (
        select(Message)
        .where(Message.session_id == session_id, Message.role == role)
        .order_by(Message.created_at.desc())
        .limit(1)
    )
    return db.scalars(stmt).first()


# =========================================================
# Feedback
# =========================================================
def get_feedback_by_session(db: Session, session_id: int) -> Optional[Feedback]:
    """
    레거시 호환: endpoint에서 positional로도 호출 가능하게 둠
    """
    stmt = select(Feedback).where(Feedback.session_id == session_id).limit(1)
    return db.scalars(stmt).first()


def upsert_feedback(
    db: Session,
    session_id: int,
    rating: Rating,
    commit: bool = True,
) -> Feedback:
    fb = get_feedback_by_session(db, session_id)
    if fb:
        fb.rating = rating
        db.add(fb)
        if commit:
            db.commit()
            db.refresh(fb)
        else:
            db.flush()
        return fb

    fb = Feedback(session_id=session_id, rating=rating)
    db.add(fb)
    if commit:
        db.commit()
        db.refresh(fb)
    else:
        db.flush()
    return fb


# ---- 레거시 alias ----
def create_feedback(db: Session, rating: Rating, session_id: int, commit: bool = True) -> Feedback:
    """
    레거시 endpoint 호환: chat.py가 create_feedback을 호출
    """
    return upsert_feedback(db, session_id=session_id, rating=rating, commit=commit)


def delete_feedback_by_session(db: Session, session_id: int, commit: bool = True) -> int:
    fb = get_feedback_by_session(db, session_id)
    if not fb:
        return 0
    db.delete(fb)
    if commit:
        db.commit()
    else:
        db.flush()
    return 1


# =========================================================
# 간단 지표
# =========================================================
def session_summary(db: Session, session_id: int) -> Dict[str, Any]:
    total = db.scalar(select(func.count()).select_from(Message).where(Message.session_id == session_id)) or 0
    users = db.scalar(
        select(func.count()).select_from(Message).where(Message.session_id == session_id, Message.role == "user")
    ) or 0
    assistants = int(total) - int(users)

    last = last_messages(db, session_id, 1)
    return {
        "messages_total": int(total),
        "messages_user": int(users),
        "messages_assistant": int(assistants),
        "last_created_at": last[0].created_at if last else None,
    }
