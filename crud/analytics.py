# crud/analytics.py
from __future__ import annotations
from datetime import datetime, timedelta, timezone
from typing import Optional, List, Dict, Any
from models.chat import ChatSession, Message
from sqlalchemy import select, func, case, literal_column, cast, Float, and_
from sqlalchemy.orm import Session
from .daily_dashboard import upsert_daily_dashboard

from models.inquiry import Inquiry
from models.model import Model


# start와 end를 구현해주는 유틸
## where 조건절로 필터를 거는데 start와 end 기간을 잡아줌.
def _range_filter(col, start: Optional[datetime], end: Optional[datetime]):
    conds = []    ## condition 약자
    if start:
        conds.append(col >= start)    ## 스타트 있으면 추가
    if end:
        conds.append(col < end)    ## End 있으면 추가
    return conds


def get_dashboard_metrics(db, *, start=None, end=None):
    # 공통 기간 조건
    cs_cond  = _range_filter(ChatSession.created_at, start, end)    # 챗세션 조건
    msg_cond = _range_filter(Message.created_at, start, end)    # 메세지
    iqc_cond = _range_filter(Inquiry.created_at, start, end)    # 상담
    iqf_cond = _range_filter(Inquiry.completed_at, start, end)    # 상담 완료

    total_sessions = db.scalar(
        select(func.count()).select_from(ChatSession).where(*cs_cond)
    ) or 0

    avg_response_ms = db.scalar(
        select(func.avg(Message.response_latency_ms).cast(Float))
        .where(Message.role == "assistant", *msg_cond)
    ) or 0.0

    # 코호트 일치형 해결률: 기간 내 "생성된" 문의 중 완료 상태 비율
    inq_total = db.scalar(
        select(func.count()).select_from(Inquiry).where(*iqc_cond)
    ) or 0
    inq_completed_in_cohort = db.scalar(
        select(func.count()).select_from(Inquiry)
        .where(Inquiry.status == "completed", *iqc_cond)
    ) or 0
    # 해결률
    resolution_rate = (inq_completed_in_cohort / inq_total) if inq_total else 0.0

    csat_rate = db.scalar(
        select(func.avg(
            case((Inquiry.customer_satisfaction == "satisfied", 1), else_=0)
        ).cast(Float)).where(Inquiry.customer_satisfaction.isnot(None), *iqc_cond)
    ) or 0.0

    # 평균 "턴": user/assistant만 포함, 1턴=유저+봇 2메시지 가정
    per_sess = (
        select(Message.session_id, func.count().label("cnt"))
        .where(Message.role.in_(("user","assistant")), *msg_cond)
        .group_by(Message.session_id)
        .subquery()
    )
    avg_msgs = db.scalar(select(func.avg(per_sess.c.cnt).cast(Float))) or 0.0
    avg_turns = avg_msgs / 2.0    # user/assistant 2건의 대화는 1개의 턴 이라서..

    session_resolved_rate = db.scalar(
        select(func.avg(cast(case((ChatSession.resolved.is_(True), 1), else_=0), Float)))
        .where(*cs_cond)
    ) or 0.0

    return {
        "total_sessions": total_sessions,
        "avg_response_ms": round(float(avg_response_ms), 2),
        "satisfaction_rate": round(float(csat_rate), 4),
        "inquiry": {
            "total": inq_total,
            "completed": inq_completed_in_cohort,
            "resolution_rate": round(float(resolution_rate), 4),
        },
        "avg_turns": round(float(avg_turns), 2),
        "session_resolved_rate": round(float(session_resolved_rate), 4),
    }


def get_daily_timeseries(db: Session, *, days: int = 30) -> List[Dict[str, Any]]:
    end = datetime.now(timezone.utc)
    start = end - timedelta(days=days)

    # 날짜 day 와 시간(time stamp) 를 분리
    bucket = func.date_trunc("day", ChatSession.created_at).label("ts")
    rows = db.execute(
        select(bucket, func.count().label("sessions"))
        .where(ChatSession.created_at >= start, ChatSession.created_at < end)
        .group_by(bucket)
        .order_by(bucket.asc())
    ).all()

    # message 즉 user 와 assistant 한줄 한줄의 metadata
    mbucket = func.date_trunc("day", Message.created_at).label("ts")
    resp_map = {
        r.ts: float(r.avg_response_ms or 0.0)
        for r in db.execute(
            select(
                mbucket,
                func.avg(cast(Message.response_latency_ms, Float)).label("avg_response_ms")
            )
            .where(
                Message.role == "assistant",
                Message.created_at >= start,
                Message.created_at < end,
            )
            .group_by(mbucket)
        ).all()
    }

    return [{"ts": r.ts, "sessions": int(r.sessions or 0),
             "avg_response_ms": round(resp_map.get(r.ts, 0.0), 2)} for r in rows]


def get_hourly_usage(db: Session, *, days: int = 7) -> List[Dict[str, Any]]:
    end = datetime.now(timezone.utc)
    start = end - timedelta(days=days)
    bucket = func.date_trunc("hour", Message.created_at).label("ts")
    rows = db.execute(
        select(bucket, func.count().label("messages"))
        .where(Message.created_at >= start, Message.created_at < end)
        .group_by(bucket)
        .order_by(bucket.asc())
    ).all()
    return [{"ts": r.ts, "messages": int(r.messages or 0)} for r in rows]


def get_model_stats(db: Session, *, limit: int = 10, start: Optional[datetime] = None, end: Optional[datetime] = None) -> List[Dict[str, Any]]:
    # 기간 필터
    cs_conds = _range_filter(ChatSession.created_at, start, end)
    ms_conds = _range_filter(Message.created_at, start, end)

    # 모델별 봇 응답 평균(ms) 서브쿼리 (모델별로 해야하나??)
    resp_agg = (
        select(
            ChatSession.model_id.label("mid"),
            func.avg(cast(Message.response_latency_ms, Float)).label("avg_ms"),
        )
        .join(Message, Message.session_id == ChatSession.id)
        .where(Message.role == "assistant", *ms_conds)
        .group_by(ChatSession.model_id)
        .subquery()
    )

    # 세션 수 집계 + 평균 응답 조인
    sessions_col = func.count(ChatSession.id).label("sessions")
    q = (
        select(
            Model.id,
            Model.name,
            Model.provider_name,
            sessions_col,
            func.coalesce(resp_agg.c.avg_ms, 0.0).label("avg_response_ms"),
        )
        .select_from(Model)
        .outerjoin(
            ChatSession,
            and_(ChatSession.model_id == Model.id, *cs_conds),
        )
        .outerjoin(resp_agg, resp_agg.c.mid == Model.id)
        .group_by(
            Model.id, Model.name, Model.provider_name, resp_agg.c.avg_ms
        )
        .order_by(sessions_col.desc(), Model.id.asc())
        .limit(limit)
    )

    rows = db.execute(q).all()
    return [
        {
            "model_id": r.id,
            "model_name": r.name,
            "provider": r.provider_name,
            "sessions": int(r.sessions or 0),
            "avg_response_ms": round(float(r.avg_response_ms or 0.0), 2),
        }
        for r in rows
    ]
