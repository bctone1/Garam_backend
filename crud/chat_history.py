# crud/chat_history.py
from __future__ import annotations

import logging
from datetime import date, datetime, time, timedelta, timezone
from typing import Optional, List, Tuple

from sqlalchemy import select, func
from sqlalchemy.orm import Session
from sqlalchemy.dialects.postgresql import insert as pg_insert

from models.chat import ChatSession, Message
from models.chat_history import ChatSessionInsight, ChatMessageInsight, ChatKeywordDaily

log = logging.getLogger("chat_history")


# =========================
# Helpers
# =========================
def _dt_range_utc(date_from: Optional[date], date_to: Optional[date]) -> Tuple[Optional[datetime], Optional[datetime]]:
    """
    date_to는 inclusive로 받고, 쿼리는 [from, to+1day) 로 처리.
    """
    dt_from = None
    dt_to_excl = None
    if date_from:
        dt_from = datetime.combine(date_from, time.min, tzinfo=timezone.utc)
    if date_to:
        dt_to_excl = datetime.combine(date_to + timedelta(days=1), time.min, tzinfo=timezone.utc)
    return dt_from, dt_to_excl


# =========================
# 1) chat_session_insight
# =========================
def get_session_insight(db: Session, session_id: int) -> Optional[ChatSessionInsight]:
    return db.get(ChatSessionInsight, session_id)


def ensure_session_insight(db: Session, session_id: int) -> ChatSessionInsight:
    """
    없으면 chat_session.created_at 기반으로 최소값 생성.
    """
    obj = db.get(ChatSessionInsight, session_id)
    if obj:
        return obj

    sess = db.get(ChatSession, session_id)
    if not sess:
        raise ValueError(f"chat_session not found: {session_id}")

    obj = ChatSessionInsight(
        session_id=session_id,
        started_at=sess.created_at,
        status="success",
        question_count=0,
    )
    db.add(obj)
    db.flush()
    return obj


def upsert_session_insight(
    db: Session,
    *,
    session_id: int,
    started_at: Optional[datetime] = None,
    channel: Optional[str] = None,
    category: Optional[str] = None,  # 캐시용 name (선택)
    quick_category_id: Optional[int] = None,  # FK (권장)
    status: Optional[str] = None,  # "success" | "failed"
    first_question: Optional[str] = None,
    question_count: Optional[int] = None,
    failed_reason: Optional[str] = None,
) -> ChatSessionInsight:
    obj = db.get(ChatSessionInsight, session_id)
    if not obj:
        # started_at 없으면 chat_session에서 채움
        sess = db.get(ChatSession, session_id)
        if not sess:
            raise ValueError(f"chat_session not found: {session_id}")
        obj = ChatSessionInsight(
            session_id=session_id,
            started_at=started_at or sess.created_at,
            channel=channel,
            category=category,
            quick_category_id=quick_category_id,
            status=status or "success",
            first_question=first_question,
            question_count=question_count or 0,
            failed_reason=failed_reason,
        )
        db.add(obj)
        db.flush()
        return obj

    if started_at is not None:
        obj.started_at = started_at
    if channel is not None:
        obj.channel = channel
    if category is not None:
        obj.category = category
    if quick_category_id is not None:
        obj.quick_category_id = int(quick_category_id)
    if status is not None:
        obj.status = status
    if first_question is not None:
        obj.first_question = first_question
    if question_count is not None:
        obj.question_count = int(question_count)
    if failed_reason is not None:
        obj.failed_reason = failed_reason

    db.flush()
    return obj


def list_session_insights(
    db: Session,
    *,
    date_from: Optional[date] = None,
    date_to: Optional[date] = None,
    status: Optional[str] = None,
    channel: Optional[str] = None,
    category: Optional[str] = None,  # 캐시 name 필터(기존 호환)
    quick_category_id: Optional[int] = None,  # FK 필터(권장)
    q: Optional[str] = None,
    offset: int = 0,
    limit: int = 50,
) -> List[ChatSessionInsight]:
    stmt = select(ChatSessionInsight)

    dt_from, dt_to_excl = _dt_range_utc(date_from, date_to)
    if dt_from:
        stmt = stmt.where(ChatSessionInsight.started_at >= dt_from)
    if dt_to_excl:
        stmt = stmt.where(ChatSessionInsight.started_at < dt_to_excl)

    if status:
        stmt = stmt.where(ChatSessionInsight.status == status)
    if channel:
        stmt = stmt.where(ChatSessionInsight.channel == channel)
    if category:
        stmt = stmt.where(ChatSessionInsight.category == category)
    if quick_category_id is not None:
        stmt = stmt.where(ChatSessionInsight.quick_category_id == int(quick_category_id))
    if q:
        like = f"%{q}%"
        stmt = stmt.where(
            (ChatSessionInsight.first_question.ilike(like)) | (ChatSessionInsight.failed_reason.ilike(like))
        )

    stmt = stmt.order_by(ChatSessionInsight.started_at.desc()).offset(offset).limit(limit)
    return db.execute(stmt).scalars().all()


def count_session_insights(
    db: Session,
    *,
    date_from: Optional[date] = None,
    date_to: Optional[date] = None,
    status: Optional[str] = None,
    channel: Optional[str] = None,
    category: Optional[str] = None,  # 캐시 name 필터(기존 호환)
    quick_category_id: Optional[int] = None,  # FK 필터(권장)
) -> int:
    stmt = select(func.count()).select_from(ChatSessionInsight)

    dt_from, dt_to_excl = _dt_range_utc(date_from, date_to)
    if dt_from:
        stmt = stmt.where(ChatSessionInsight.started_at >= dt_from)
    if dt_to_excl:
        stmt = stmt.where(ChatSessionInsight.started_at < dt_to_excl)

    if status:
        stmt = stmt.where(ChatSessionInsight.status == status)
    if channel:
        stmt = stmt.where(ChatSessionInsight.channel == channel)
    if category:
        stmt = stmt.where(ChatSessionInsight.category == category)
    if quick_category_id is not None:
        stmt = stmt.where(ChatSessionInsight.quick_category_id == int(quick_category_id))

    return int(db.execute(stmt).scalar_one())


# =========================
# 2) chat_message_insight
# =========================
def get_message_insight(db: Session, message_id: int) -> Optional[ChatMessageInsight]:
    return db.get(ChatMessageInsight, message_id)


def ensure_message_insight(db: Session, message_id: int) -> ChatMessageInsight:
    """
    없으면 message 기반으로 최소값 생성(user면 is_question=true 가정).
    """
    obj = db.get(ChatMessageInsight, message_id)
    if obj:
        return obj

    msg = db.get(Message, message_id)
    if not msg:
        raise ValueError(f"message not found: {message_id}")

    obj = ChatMessageInsight(
        message_id=message_id,
        session_id=msg.session_id,
        is_question=(msg.role == "user"),
        keywords=None,
        category=None,
        created_at=msg.created_at,
    )
    db.add(obj)
    db.flush()
    return obj


def upsert_message_insight(
    db: Session,
    *,
    message_id: int,
    session_id: Optional[int] = None,
    is_question: Optional[bool] = None,
    category: Optional[str] = None,
    keywords: Optional[List[str]] = None,
    created_at: Optional[datetime] = None,
) -> ChatMessageInsight:
    obj = db.get(ChatMessageInsight, message_id)
    if not obj:
        # 필요한 필드 보강
        if session_id is None or created_at is None:
            msg = db.get(Message, message_id)
            if not msg:
                raise ValueError(f"message not found: {message_id}")
            session_id = session_id or msg.session_id
            created_at = created_at or msg.created_at
            if is_question is None:
                is_question = (msg.role == "user")

        obj = ChatMessageInsight(
            message_id=message_id,
            session_id=int(session_id),  # type: ignore[arg-type]
            is_question=bool(is_question) if is_question is not None else True,
            category=category,
            keywords=keywords,
            created_at=created_at,  # type: ignore[arg-type]
        )
        db.add(obj)
        db.flush()
        return obj

    if session_id is not None:
        obj.session_id = int(session_id)
    if is_question is not None:
        obj.is_question = bool(is_question)
    if category is not None:
        obj.category = category
    if keywords is not None:
        obj.keywords = keywords
    if created_at is not None:
        obj.created_at = created_at

    db.flush()
    return obj


def list_message_insights(
    db: Session,
    *,
    date_from: Optional[date] = None,
    date_to: Optional[date] = None,
    session_id: Optional[int] = None,
    channel: Optional[str] = None,
    category: Optional[str] = None,
    offset: int = 0,
    limit: int = 50,
) -> List[ChatMessageInsight]:
    stmt = select(ChatMessageInsight)

    dt_from, dt_to_excl = _dt_range_utc(date_from, date_to)
    if dt_from:
        stmt = stmt.where(ChatMessageInsight.created_at >= dt_from)
    if dt_to_excl:
        stmt = stmt.where(ChatMessageInsight.created_at < dt_to_excl)

    if session_id is not None:
        stmt = stmt.where(ChatMessageInsight.session_id == session_id)
    if category:
        stmt = stmt.where(ChatMessageInsight.category == category)

    # channel 필터는 session_insight join으로 처리(메시지 인사이트에 channel을 저장 안 했으니까)
    if channel:
        stmt = stmt.join(
            ChatSessionInsight,
            ChatSessionInsight.session_id == ChatMessageInsight.session_id,
        ).where(ChatSessionInsight.channel == channel)

    stmt = stmt.order_by(ChatMessageInsight.created_at.desc()).offset(offset).limit(limit)
    return db.execute(stmt).scalars().all()


# =========================
# 3) chat_keyword_daily
# =========================
def list_keyword_daily(
    db: Session,
    *,
    date_from: Optional[date] = None,
    date_to: Optional[date] = None,
    channel: Optional[str] = None,
    quick_category_id: Optional[int] = None,
    top_n: int = 100,
) -> List[ChatKeywordDaily]:
    stmt = select(ChatKeywordDaily)

    if date_from:
        stmt = stmt.where(ChatKeywordDaily.dt >= date_from)
    if date_to:
        stmt = stmt.where(ChatKeywordDaily.dt <= date_to)

    if channel:
        stmt = stmt.where(ChatKeywordDaily.channel == channel)
    if quick_category_id is not None:
        stmt = stmt.where(ChatKeywordDaily.quick_category_id == int(quick_category_id))

    stmt = stmt.order_by(ChatKeywordDaily.count.desc(), ChatKeywordDaily.keyword.asc()).limit(int(top_n))
    return db.execute(stmt).scalars().all()


def upsert_keyword_daily_set(
    db: Session,
    *,
    dt: date,
    keyword: str,
    count: int,
    channel: Optional[str] = None,
    quick_category_id: Optional[int] = None,
) -> None:
    """
    (dt, keyword, channel, quick_category_id) 유니크키 기준으로 count를 '설정' (재빌드/ETL에 적합)
    """
    stmt = (
        pg_insert(ChatKeywordDaily)
        .values(
            dt=dt,
            keyword=keyword,
            count=int(count),
            channel=channel,
            quick_category_id=quick_category_id,
        )
        .on_conflict_do_update(
            constraint="uq_chat_kw_daily",
            set_={
                "count": int(count),
                "updated_at": func.now(),
            },
        )
    )
    db.execute(stmt)


def upsert_keyword_daily_add(
    db: Session,
    *,
    dt: date,
    keyword: str,
    delta: int,
    channel: Optional[str] = None,
    quick_category_id: Optional[int] = None,
) -> None:
    """
    (dt, keyword, channel, quick_category_id) 유니크키 기준으로 count를 '증가' (실시간 누적에 적합)
    """
    delta_i = int(delta)
    stmt = (
        pg_insert(ChatKeywordDaily)
        .values(
            dt=dt,
            keyword=keyword,
            count=delta_i,
            channel=channel,
            quick_category_id=quick_category_id,
        )
        .on_conflict_do_update(
            constraint="uq_chat_kw_daily",
            set_={
                "count": ChatKeywordDaily.count + delta_i,
                "updated_at": func.now(),
            },
        )
    )
    db.execute(stmt)


def delete_keyword_daily_range(
    db: Session,
    *,
    date_from: date,
    date_to: date,
    channel: Optional[str] = None,
    quick_category_id: Optional[int] = None,
) -> int:
    """
    기간 재집계 전에 기존 집계 제거용.
    """
    q = db.query(ChatKeywordDaily).filter(ChatKeywordDaily.dt >= date_from, ChatKeywordDaily.dt <= date_to)
    if channel:
        q = q.filter(ChatKeywordDaily.channel == channel)
    if quick_category_id is not None:
        q = q.filter(ChatKeywordDaily.quick_category_id == int(quick_category_id))
    n = q.delete(synchronize_session=False)
    return int(n)


__all__ = [
    "get_session_insight",
    "ensure_session_insight",
    "upsert_session_insight",
    "list_session_insights",
    "count_session_insights",
    "get_message_insight",
    "ensure_message_insight",
    "upsert_message_insight",
    "list_message_insights",
    "list_keyword_daily",
    "upsert_keyword_daily_set",
    "upsert_keyword_daily_add",
    "delete_keyword_daily_range",
]
