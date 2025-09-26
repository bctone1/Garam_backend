from __future__ import annotations
from datetime import datetime, timedelta
from typing import Optional, List, Dict, Any

from sqlalchemy import select, func, case, literal_column
from sqlalchemy.orm import Session

from models.chat import ChatSession, Message
from models.inquiry import Inquiry
from models.model import Model


def _range_filter(col, start: Optional[datetime], end: Optional[datetime]):
    conds = []    ## condition 약자
    if start:
        conds.append(col >= start)    ## 스타트 있으면 추가
    if end:
        conds.append(col < end)    ## End 있으면 추가
    return conds


def get_dashboard_metrics(
    db: Session, *, start: Optional[datetime] = None, end: Optional[datetime] = None
) -> Dict[str, Any]:
    # 총 세션
    total_sessions = db.scalar(
        select(func.count()).select_from(ChatSession).where(*_range_filter(ChatSession.created_at, start, end))
    ) or 0

    # 평균 응답(ms) - bot 메시지
    avg_response_ms = float(db.scalar(
        select(func.avg(Message.response_latency_ms.cast(float)))
        .where(Message.role == "bot", *_range_filter(Message.created_at, start, end))
    ) or 0.0)

    # 문의 해결률
    inq_total = db.scalar(
        select(func.count()).select_from(Inquiry).where(*_range_filter(Inquiry.created_at, start, end))
    ) or 0
    inq_completed = db.scalar(
        select(func.count()).select_from(Inquiry).where(
            Inquiry.status == "completed", *_range_filter(Inquiry.completed_at, start, end)
        )
    ) or 0
    inquiry_resolution_rate = (inq_completed / inq_total) if inq_total else 0.0

    # 만족도(고객 설문) → Inquiry.customer_satisfaction 기반
    csat_rate = float(db.scalar(
        select(func.avg(case((Inquiry.customer_satisfaction == "satisfied", 1), else_=0).cast(float)))
        .where(Inquiry.customer_satisfaction.isnot(None), *_range_filter(Inquiry.created_at, start, end))
    ) or 0.0)

    # 세션당 평균 턴 수
    msg_per_session = (
        select(Message.session_id, func.count().label("cnt"))
        .where(*_range_filter(Message.created_at, start, end))
        .group_by(Message.session_id)
        .subquery()
    )
    #
    avg_turns = float(db.scalar(select(func.avg(literal_column("cnt").cast(float))).select_from(msg_per_session)) or 0.0)

    # 완료된 세션 비율
    session_resolved_rate = float(db.scalar(
        select(func.avg(case((ChatSession.resolved.is_(True), 1), else_=0).cast(float)))
        .where(*_range_filter(ChatSession.created_at, start, end))
    ) or 0.0)

    return {
        "total_sessions": total_sessions,
        "avg_response_ms": round(avg_response_ms, 2),
        "satisfaction_rate": round(csat_rate, 4),
        "inquiry": {
            "total": inq_total,
            "completed": inq_completed,
            "resolution_rate": round(inquiry_resolution_rate, 4),
        },
        "avg_turns": round(avg_turns, 2),
        "session_resolved_rate": round(session_resolved_rate, 4),
    }


def get_daily_timeseries(db: Session, *, days: int = 30) -> List[Dict[str, Any]]:
    end = datetime.datetime.now(datetime.UTC)
    start = end - timedelta(days=days)

    bucket = func.date_trunc("day", ChatSession.created_at).label("ts")
    rows = db.execute(
        select(bucket, func.count().label("sessions"))
        .where(ChatSession.created_at >= start, ChatSession.created_at < end)
        .group_by(bucket)
        .order_by(bucket.asc())
    ).all()

    mbucket = func.date_trunc("day", Message.created_at).label("ts")
    resp_map = {
        r.ts: float(r.avg_response_ms or 0.0)
        for r in db.execute(
            select(mbucket, func.avg(Message.response_latency_ms.cast(float)).label("avg_response_ms"))
            .where(Message.role == "bot", Message.created_at >= start, Message.created_at < end)
            .group_by(mbucket)
        ).all()
    }

    return [{"ts": r.ts, "sessions": int(r.sessions or 0), "avg_response_ms": round(resp_map.get(r.ts, 0.0), 2)} for r in rows]


def get_hourly_usage(db: Session, *, days: int = 7) -> List[Dict[str, Any]]:
    end = datetime.datetime.now(datetime.UTC)
    start = end - timedelta(days=days)
    bucket = func.date_trunc("hour", Message.created_at).label("ts")
    rows = db.execute(
        select(bucket, func.count().label("messages"))
        .where(Message.created_at >= start, Message.created_at < end)
        .group_by(bucket)
        .order_by(bucket.asc())
    ).all()
    return [{"ts": r.ts, "messages": int(r.messages or 0)} for r in rows]


def get_model_stats(db: Session, *, limit: int = 10) -> List[Dict[str, Any]]:
    base = db.execute(
        select(Model.id, Model.name, Model.provider_name, func.count(ChatSession.id).label("sessions"))
        .join(ChatSession, ChatSession.model_id == Model.id, isouter=True)
        .group_by(Model.id)
        .order_by(literal_column("sessions").desc(), Model.created_at.desc())
        .limit(limit)
    ).all()

    resp_map = {
        mid: float(avg or 0.0)
        for mid, avg in db.execute(
            select(ChatSession.model_id.label("mid"), func.avg(Message.response_latency_ms.cast(float)).label("avg_ms"))
            .join(Message, Message.session_id == ChatSession.id)
            .where(Message.role == "bot")
            .group_by(ChatSession.model_id)
        ).all()
    }

    return [
        {
            "model_id": r.id,
            "model_name": r.name,
            "provider": r.provider_name,
            "sessions": int(r.sessions or 0),
            "avg_response_ms": round(resp_map.get(r.id, 0.0), 2),
        }
        for r in base
    ]
