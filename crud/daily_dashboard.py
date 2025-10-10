# crud/daily_dashboard.py
from __future__ import annotations
from datetime import date, timedelta
from typing import List, Dict
from sqlalchemy import text, select, and_, func
from sqlalchemy.orm import Session
from models.daily_dashboard import DailyDashboard


# KST 기준 집계 업서트
def upsert_daily_dashboard(db: Session, *, start: date, end: date) -> None:
    sql = text("""
    WITH days AS (
      SELECT g::date AS d
      FROM generate_series(CAST(:start AS date), CAST(:end AS date), interval '1 day') AS g
    ),
    -- 세션(범위 제한)
    cs AS (
      SELECT
        id,
        (created_at AT TIME ZONE 'Asia/Seoul')::date AS d,
        (created_at AT TIME ZONE 'Asia/Seoul')::time AS t,
        resolved
      FROM chat_session
      WHERE (created_at AT TIME ZONE 'Asia/Seoul')::date
            BETWEEN CAST(:start AS date) AND CAST(:end AS date)
    ),
    cs_hour AS (
      SELECT d, EXTRACT(HOUR FROM t)::int AS h, COUNT(*) AS c
      FROM cs
      GROUP BY d, h
    ),
    hour_filled AS (
      SELECT d.d,
             jsonb_object_agg(gs.h::text, COALESCE(ch.c,0)) AS j
      FROM days d
      CROSS JOIN generate_series(0,23) AS gs(h)
      LEFT JOIN cs_hour ch ON ch.d = d.d AND ch.h = gs.h
      GROUP BY d.d
    ),
    -- 메시지(범위 제한, user/assistant만)
    msg AS (
      SELECT
        (created_at AT TIME ZONE 'Asia/Seoul')::date AS d,
        session_id, role, response_latency_ms
      FROM message
      WHERE role IN ('assistant','user')
        AND (created_at AT TIME ZONE 'Asia/Seoul')::date
            BETWEEN CAST(:start AS date) AND CAST(:end AS date)
    ),
    -- assistant 응답지연 통계
    assistant_latency AS (
      SELECT d,
             AVG(response_latency_ms)::numeric(10,2) AS avg_ms,
             percentile_cont(0.5) WITHIN GROUP (ORDER BY response_latency_ms)::numeric(10,2) AS p50_ms,
             percentile_cont(0.9) WITHIN GROUP (ORDER BY response_latency_ms)::numeric(10,2) AS p90_ms
      FROM msg
      WHERE role='assistant'
      GROUP BY d
    ),
    -- 그 날 어시스턴트가 1번이라도 답한 세션들
    assistant_sessions AS (
      SELECT d, session_id
      FROM msg
      WHERE role='assistant'
      GROUP BY d, session_id
    ),
    -- 턴 수(유저/어시스턴트 메시지 수 기준 2개=1턴 가정)
    turns AS (
      SELECT d, session_id, floor(COUNT(*) FILTER (WHERE role IN ('user','assistant'))/2.0) AS t
      FROM msg
      GROUP BY d, session_id
    ),
    turns_avg AS (
      SELECT d, COALESCE(AVG(t),0)::numeric(6,2) AS avg_turns
      FROM turns
      GROUP BY d
    ),
    -- 피드백(범위 제한)
    fb AS (
      SELECT
        (created_at AT TIME ZONE 'Asia/Seoul')::date AS d,
        SUM(CASE WHEN rating='helpful' THEN 1 ELSE 0 END)     AS helpful,
        SUM(CASE WHEN rating='not_helpful' THEN 1 ELSE 0 END) AS not_helpful
      FROM feedback
      WHERE (created_at AT TIME ZONE 'Asia/Seoul')::date
            BETWEEN CAST(:start AS date) AND CAST(:end AS date)
      GROUP BY 1
    ),
    -- 문의(범위 제한)
    iq AS (
      SELECT
        (created_at AT TIME ZONE 'Asia/Seoul')::date AS d,
        COUNT(*) AS cnt
      FROM inquiry
      WHERE (created_at AT TIME ZONE 'Asia/Seoul')::date
            BETWEEN CAST(:start AS date) AND CAST(:end AS date)
      GROUP BY 1
    ),
    -- 일자별 최종 집계
    agg AS (
      SELECT
        d.d,
        EXTRACT(ISODOW FROM d.d)::smallint AS weekday,
        COALESCE((SELECT COUNT(*) FROM cs WHERE cs.d = d.d), 0) AS sessions_total,
        COALESCE((SELECT COUNT(*) FROM assistant_sessions WHERE assistant_sessions.d = d.d), 0) AS sessions_with_assistant,
        -- 스키마상 resolved_at 미정 → 생성일 기준 + resolved=true 로 집계 유지
        COALESCE((SELECT COUNT(*) FROM cs WHERE cs.d = d.d AND cs.resolved IS TRUE), 0) AS sessions_resolved,
        COALESCE((SELECT COUNT(*) FROM msg WHERE msg.d = d.d), 0) AS messages_total,
        COALESCE((SELECT avg_ms FROM assistant_latency WHERE assistant_latency.d = d.d), 0)::numeric(10,2) AS avg_response_ms,
        COALESCE((SELECT p50_ms FROM assistant_latency WHERE assistant_latency.d = d.d), 0)::numeric(10,2) AS p50_response_ms,
        COALESCE((SELECT p90_ms FROM assistant_latency WHERE assistant_latency.d = d.d), 0)::numeric(10,2) AS p90_response_ms,
        COALESCE((SELECT avg_turns FROM turns_avg WHERE turns_avg.d = d.d), 0)::numeric(6,2) AS avg_turns,
        COALESCE((SELECT cnt FROM iq WHERE iq.d = d.d), 0) AS inquiries_created,
        COALESCE((SELECT helpful FROM fb WHERE fb.d = d.d), 0) AS feedback_helpful,
        COALESCE((SELECT not_helpful FROM fb WHERE fb.d = d.d), 0) AS feedback_not_helpful,
        COALESCE((SELECT j FROM hour_filled WHERE hour_filled.d = d.d), '{}'::jsonb) AS sessions_by_hour
      FROM days d
    )
    INSERT INTO daily_dashboard AS dd
      (d, weekday, sessions_total, sessions_with_assistant, sessions_resolved,
       messages_total, avg_response_ms, p50_response_ms, p90_response_ms,
       avg_turns, inquiries_created, feedback_helpful, feedback_not_helpful, sessions_by_hour, updated_at)
    SELECT
      a.d, a.weekday, a.sessions_total, a.sessions_with_assistant, a.sessions_resolved,
      a.messages_total, a.avg_response_ms, a.p50_response_ms, a.p90_response_ms,
      a.avg_turns, a.inquiries_created, a.feedback_helpful, a.feedback_not_helpful, a.sessions_by_hour, now()
    FROM agg a
    ON CONFLICT (d) DO UPDATE SET
      weekday              = EXCLUDED.weekday,
      sessions_total       = EXCLUDED.sessions_total,
      sessions_with_assistant = EXCLUDED.sessions_with_assistant,
      sessions_resolved    = EXCLUDED.sessions_resolved,
      messages_total       = EXCLUDED.messages_total,
      avg_response_ms      = EXCLUDED.avg_response_ms,
      p50_response_ms      = EXCLUDED.p50_response_ms,
      p90_response_ms      = EXCLUDED.p90_response_ms,
      avg_turns            = EXCLUDED.avg_turns,
      inquiries_created    = EXCLUDED.inquiries_created,
      feedback_helpful     = EXCLUDED.feedback_helpful,
      feedback_not_helpful = EXCLUDED.feedback_not_helpful,
      sessions_by_hour     = EXCLUDED.sessions_by_hour,
      updated_at           = now();
    """)
    db.execute(sql, {"start": start, "end": end})
    db.commit()


# d 구간 조회. include_today=True면 오늘은 즉시산출로 합치기
def list_daily(db: Session, *, start: date, end: date, include_today: bool = True) -> List[DailyDashboard]:
    if not include_today:
        q = (
            select(DailyDashboard)
            .where(and_(DailyDashboard.d >= start, DailyDashboard.d <= end))
            .order_by(DailyDashboard.d.desc())
        )
        return list(db.scalars(q).all())

    sql = text("""
    WITH kst_today AS (
      SELECT (now() AT TIME ZONE 'Asia/Seoul')::date AS d
    ),
    today AS (
      SELECT
        kt.d AS d,
        EXTRACT(ISODOW FROM kt.d)::smallint AS weekday,
        (SELECT COUNT(*) FROM chat_session s
          WHERE (s.created_at AT TIME ZONE 'Asia/Seoul')::date = kt.d) AS sessions_total,
        (SELECT COUNT(DISTINCT m.session_id) FROM message m
          WHERE m.role='assistant'
            AND (m.created_at AT TIME ZONE 'Asia/Seoul')::date = kt.d) AS sessions_with_assistant,
        (SELECT COUNT(*) FROM chat_session s
          WHERE s.resolved IS TRUE
            AND (s.created_at AT TIME ZONE 'Asia/Seoul')::date = kt.d) AS sessions_resolved,
        (SELECT COUNT(*) FROM message m
          WHERE m.role IN ('user','assistant')
            AND (m.created_at AT TIME ZONE 'Asia/Seoul')::date = kt.d) AS messages_total,
        (SELECT COALESCE(AVG(response_latency_ms),0)::numeric(10,2)
          FROM message WHERE role='assistant'
            AND (created_at AT TIME ZONE 'Asia/Seoul')::date = kt.d) AS avg_response_ms,
        (SELECT COALESCE(
            percentile_cont(0.5) WITHIN GROUP (ORDER BY response_latency_ms),
            0
         ) FROM message WHERE role='assistant'
            AND (created_at AT TIME ZONE 'Asia/Seoul')::date = kt.d
        )::numeric(10,2) AS p50_response_ms,
        (SELECT COALESCE(
            percentile_cont(0.9) WITHIN GROUP (ORDER BY response_latency_ms),
            0
         ) FROM message WHERE role='assistant'
            AND (created_at AT TIME ZONE 'Asia/Seoul')::date = kt.d
        )::numeric(10,2) AS p90_response_ms,
        (SELECT COALESCE(AVG(floor(cnt/2.0)),0)::numeric(6,2) FROM (
            SELECT session_id, COUNT(*) FILTER (WHERE role IN ('user','assistant')) AS cnt
            FROM message
            WHERE (created_at AT TIME ZONE 'Asia/Seoul')::date = kt.d
            GROUP BY session_id
        ) t) AS avg_turns,
        (SELECT COUNT(*) FROM inquiry
          WHERE (created_at AT TIME ZONE 'Asia/Seoul')::date = kt.d) AS inquiries_created,
        (SELECT COUNT(*) FROM feedback
          WHERE rating='helpful'
            AND (created_at AT TIME ZONE 'Asia/Seoul')::date = kt.d) AS feedback_helpful,
        (SELECT COUNT(*) FROM feedback
          WHERE rating='not_helpful'
            AND (created_at AT TIME ZONE 'Asia/Seoul')::date = kt.d) AS feedback_not_helpful,
        (
          SELECT jsonb_object_agg(x.h::text, COALESCE(x.c,0)) FROM (
            SELECT gs.h,
              (
                SELECT COUNT(*) FROM chat_session s2
                WHERE (s2.created_at AT TIME ZONE 'Asia/Seoul')::date = kt.d
                  AND EXTRACT(HOUR FROM (s2.created_at AT TIME ZONE 'Asia/Seoul'))::int = gs.h
              ) AS c
            FROM generate_series(0,23) AS gs(h)
          ) x
        ) AS sessions_by_hour,
        now() AS updated_at
      FROM kst_today kt
    )
    SELECT * FROM daily_dashboard
      WHERE d BETWEEN CAST(:start AS date) AND ((SELECT d FROM kst_today) - INTERVAL '1 day')::date
    UNION ALL
    SELECT * FROM today
    ORDER BY d DESC;
    """)
    rows = db.execute(sql, {"start": start}).mappings().all()
    return [DailyDashboard(**r) for r in rows]


def window_averages(db: Session, *, days: int) -> Dict[str, float]:
    # KST 기준 최근 N일
    sql = text("""
      SELECT
        COALESCE(AVG(sessions_total), 0)::float8,
        COALESCE(AVG(messages_total), 0)::float8,
        COALESCE(AVG(avg_response_ms), 0)::float8,
        COALESCE(AVG(avg_turns), 0)::float8,
        COALESCE(SUM(sessions_resolved), 0)::int,
        COALESCE(SUM(sessions_with_assistant), 0)::int,
        COALESCE(SUM(feedback_helpful), 0)::int,
        COALESCE(SUM(feedback_not_helpful), 0)::int
      FROM daily_dashboard
      WHERE d >= (((now() AT TIME ZONE 'Asia/Seoul'))::date - (CAST(:days AS int) - 1))
    """)
    s, m, rt, t, resolved, with_asst, helpf, nhelpf = db.execute(sql, {"days": days}).one()

    f = lambda x: float(x or 0)
    resolve_rate = float(resolved or 0) / float(with_asst or 1)
    csat_rate    = float(helpf or 0) / float(((helpf or 0) + (nhelpf or 0)) or 1)
    return {
        "avg_sessions": f(s),
        "avg_messages": f(m),
        "avg_response_ms": f(rt),
        "avg_turns": f(t),
        "resolve_rate_excluding_noresp": resolve_rate,
        "csat_rate": csat_rate,
    }
