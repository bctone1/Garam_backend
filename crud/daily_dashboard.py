from __future__ import annotations
from datetime import date, timedelta
from typing import List, Dict
from sqlalchemy import text, select, and_, func
from sqlalchemy.orm import Session
from models.daily_dashboard import DailyDashboard

# KST 날짜 기준 집계 업서트
def upsert_daily_dashboard(db: Session, *, start: date, end: date) -> None:
    sql = text("""
    WITH days AS (
      SELECT g::date AS d FROM generate_series(:start::date, :end::date, interval '1 day') g
    ),
    cs AS (
      SELECT id,
             ((created_at AT TIME ZONE 'UTC' AT TIME ZONE 'Asia/Seoul'))::date AS d,
             ((created_at AT TIME ZONE 'UTC' AT TIME ZONE 'Asia/Seoul'))::time AS t,
             resolved
      FROM chat_session
    ),
    cs_hour AS (
      SELECT d, EXTRACT(HOUR FROM t)::int AS h, COUNT(*) AS c
      FROM cs GROUP BY d, h
    ),
    hour_filled AS (
      SELECT d.d,
             jsonb_object_agg(h::text, COALESCE(ch.c,0)) AS j
      FROM days d
      CROSS JOIN generate_series(0,23) AS h(h)
      LEFT JOIN cs_hour ch ON ch.d = d.d AND ch.h = h.h
      GROUP BY d.d
    ),
    msg AS (
      SELECT ((created_at AT TIME ZONE 'UTC' AT TIME ZONE 'Asia/Seoul'))::date AS d,
             session_id, role, response_latency_ms
      FROM message
      WHERE role IN ('assistant','user')
    ),
    bot_latency AS (
      SELECT d,
             AVG(response_latency_ms)::numeric(10,2) AS avg_ms,
             percentile_cont(0.5) WITHIN GROUP (ORDER BY response_latency_ms)::numeric(10,2) AS p50_ms,
             percentile_cont(0.9) WITHIN GROUP (ORDER BY response_latency_ms)::numeric(10,2) AS p90_ms
      FROM msg WHERE role='assistant'
      GROUP BY d
    ),
    bot_sessions AS (SELECT d, session_id FROM msg WHERE role='assistant' GROUP BY d, session_id),
    turns AS (
      SELECT d, session_id, floor(count(*)/2.0) AS t
      FROM msg GROUP BY d, session_id
    ),
    turns_avg AS (SELECT d, COALESCE(AVG(t),0)::numeric(6,2) AS avg_turns FROM turns GROUP BY d),
    fb AS (
      SELECT ((created_at AT TIME ZONE 'UTC' AT TIME ZONE 'Asia/Seoul'))::date AS d,
             SUM(CASE WHEN rating='helpful' THEN 1 ELSE 0 END) AS helpful,
             SUM(CASE WHEN rating='not_helpful' THEN 1 ELSE 0 END) AS not_helpful
      FROM feedback GROUP BY 1
    ),
    iq AS (
      SELECT ((created_at AT TIME ZONE 'UTC' AT TIME ZONE 'Asia/Seoul'))::date AS d, COUNT(*) AS cnt
      FROM inquiry GROUP BY 1
    ),
    agg AS (
      SELECT
        d.d,
        EXTRACT(ISODOW FROM d.d)::smallint AS weekday,
        COALESCE((SELECT COUNT(*) FROM cs WHERE cs.d = d.d),0) AS sessions_total,
        COALESCE((SELECT COUNT(*) FROM bot_sessions WHERE bot_sessions.d = d.d),0) AS sessions_with_bot,
        COALESCE((SELECT COUNT(*) FROM cs WHERE cs.d = d.d AND cs.resolved IS TRUE),0) AS sessions_resolved,
        COALESCE((SELECT COUNT(*) FROM msg WHERE msg.d = d.d),0) AS messages_total,
        COALESCE((SELECT avg_ms FROM bot_latency WHERE bot_latency.d = d.d),0)::numeric(10,2) AS avg_response_ms,
        COALESCE((SELECT p50_ms FROM bot_latency WHERE bot_latency.d = d.d),0)::numeric(10,2) AS p50_response_ms,
        COALESCE((SELECT p90_ms FROM bot_latency WHERE bot_latency.d = d.d),0)::numeric(10,2) AS p90_response_ms,
        COALESCE((SELECT avg_turns FROM turns_avg WHERE turns_avg.d = d.d),0)::numeric(6,2) AS avg_turns,
        COALESCE((SELECT cnt FROM iq WHERE iq.d = d.d),0) AS inquiries_created,
        COALESCE((SELECT helpful FROM fb WHERE fb.d = d.d),0) AS feedback_helpful,
        COALESCE((SELECT not_helpful FROM fb WHERE fb.d = d.d),0) AS feedback_not_helpful,
        COALESCE((SELECT j FROM hour_filled WHERE hour_filled.d = d.d), '{}'::jsonb) AS sessions_by_hour
      FROM days d
    )
    INSERT INTO daily_dashboard
      (d, weekday, sessions_total, sessions_with_bot, sessions_resolved,
       messages_total, avg_response_ms, p50_response_ms, p90_response_ms,
       avg_turns, inquiries_created, feedback_helpful, feedback_not_helpful, sessions_by_hour)
    SELECT * FROM agg
    ON CONFLICT (d) DO UPDATE SET
      weekday=EXCLUDED.weekday,
      sessions_total=EXCLUDED.sessions_total,
      sessions_with_bot=EXCLUDED.sessions_with_bot,
      sessions_resolved=EXCLUDED.sessions_resolved,
      messages_total=EXCLUDED.messages_total,
      avg_response_ms=EXCLUDED.avg_response_ms,
      p50_response_ms=EXCLUDED.p50_response_ms,
      p90_response_ms=EXCLUDED.p90_response_ms,
      avg_turns=EXCLUDED.avg_turns,
      inquiries_created=EXCLUDED.inquiries_created,
      feedback_helpful=EXCLUDED.feedback_helpful,
      feedback_not_helpful=EXCLUDED.feedback_not_helpful,
      sessions_by_hour=EXCLUDED.sessions_by_hour,
      updated_at=now();
    """)
    db.execute(sql, {"start": start, "end": end})
    db.commit()

# d 구간 조회. include_today=True면 오늘은 즉시산출로 합치기
def list_daily(db: Session, *, start: date, end: date, include_today: bool = True) -> List[DailyDashboard]:
    if not include_today:
        q = (select(DailyDashboard)
             .where(and_(DailyDashboard.d >= start, DailyDashboard.d <= end))
             .order_by(DailyDashboard.d.desc()))
        return list(db.scalars(q).all())

    sql = text("""
    WITH kst_today AS (SELECT (now() AT TIME ZONE 'Asia/Seoul')::date AS d),
    today AS (
      SELECT
        kt.d AS d,
        EXTRACT(ISODOW FROM kt.d)::smallint AS weekday,
        (SELECT COUNT(*) FROM chat_session s
          WHERE ((s.created_at AT TIME ZONE 'UTC' AT TIME ZONE 'Asia/Seoul'))::date = kt.d) AS sessions_total,
        (SELECT COUNT(DISTINCT m.session_id) FROM message m
          WHERE m.role='assistant'
            AND ((m.created_at AT TIME ZONE 'UTC' AT TIME ZONE 'Asia/Seoul'))::date = kt.d) AS sessions_with_bot,
        (SELECT COUNT(*) FROM chat_session s
          WHERE s.resolved IS TRUE
            AND ((s.created_at AT TIME ZONE 'UTC' AT TIME ZONE 'Asia/Seoul'))::date = kt.d) AS sessions_resolved,
        (SELECT COUNT(*) FROM message m
          WHERE m.role IN ('user','assistant')
            AND ((m.created_at AT TIME ZONE 'UTC' AT TIME ZONE 'Asia/Seoul'))::date = kt.d) AS messages_total,
        (SELECT COALESCE(AVG(response_latency_ms),0)::numeric(10,2)
          FROM message WHERE role='assistant'
            AND ((created_at AT TIME ZONE 'UTC' AT TIME ZONE 'Asia/Seoul'))::date = kt.d) AS avg_response_ms,
        (SELECT percentile_cont(0.5) WITHIN GROUP (ORDER BY response_latency_ms)
          FROM message WHERE role='assistant'
            AND ((created_at AT TIME ZONE 'UTC' AT TIME ZONE 'Asia/Seoul'))::date = kt.d)::numeric(10,2) AS p50_response_ms,
        (SELECT percentile_cont(0.9) WITHIN GROUP (ORDER BY response_latency_ms)
          FROM message WHERE role='assistant'
            AND ((created_at AT TIME ZONE 'UTC' AT TIME ZONE 'Asia/Seoul'))::date = kt.d)::numeric(10,2) AS p90_response_ms,
        (SELECT COALESCE(AVG(floor(cnt/2.0)),0)::numeric(6,2) FROM (
            SELECT session_id, COUNT(*) FILTER (WHERE role IN ('user','assistant')) AS cnt
            FROM message
            WHERE ((created_at AT TIME ZONE 'UTC' AT TIME ZONE 'Asia/Seoul'))::date = kt.d
            GROUP BY session_id
        ) t) AS avg_turns,
        (SELECT COUNT(*) FROM inquiry
          WHERE ((created_at AT TIME ZONE 'UTC' AT TIME ZONE 'Asia/Seoul'))::date = kt.d) AS inquiries_created,
        (SELECT COUNT(*) FROM feedback
          WHERE rating='helpful'
            AND ((created_at AT TIME ZONE 'UTC' AT TIME ZONE 'Asia/Seoul'))::date = kt.d) AS feedback_helpful,
        (SELECT COUNT(*) FROM feedback
          WHERE rating='not_helpful'
            AND ((created_at AT TIME ZONE 'UTC' AT TIME ZONE 'Asia/Seoul'))::date = kt.d) AS feedback_not_helpful,
        (
          SELECT jsonb_object_agg(h::text, COALESCE(c,0)) FROM (
            SELECT h, (
              SELECT COUNT(*) FROM chat_session s2
              WHERE ((s2.created_at AT TIME ZONE 'UTC' AT TIME ZONE 'Asia/Seoul'))::date = kt.d
                AND EXTRACT(HOUR FROM ((s2.created_at AT TIME ZONE 'UTC' AT TIME ZONE 'Asia/Seoul')))::int = h
            ) AS c
            FROM generate_series(0,23) h
          ) x
        ) AS sessions_by_hour,
        now() AT TIME ZONE 'Asia/Seoul' AS updated_at
      FROM kst_today kt
    )
    SELECT * FROM daily_dashboard
      WHERE d BETWEEN :start AND (SELECT d FROM kst_today) - INTERVAL '1 day'
    UNION ALL
    SELECT * FROM today
    ORDER BY d DESC;
    """)
    rows = db.execute(sql, {"start": start}).mappings().all()
    # 매핑 → Pydantic 변환은 라우터에서 처리
    return [DailyDashboard(**r) for r in rows]

def window_averages(db: Session, *, days: int) -> Dict[str, float]:
    start = date.today() - timedelta(days=days - 1)
    q = select(
        func.avg(DailyDashboard.sessions_total),
        func.avg(DailyDashboard.messages_total),
        func.avg(DailyDashboard.avg_response_ms),
        func.avg(DailyDashboard.avg_turns),
        func.sum(DailyDashboard.sessions_resolved),
        func.sum(DailyDashboard.sessions_with_bot),
        func.sum(DailyDashboard.feedback_helpful),
        func.sum(DailyDashboard.feedback_not_helpful),
    ).where(DailyDashboard.d >= start)
    s, m, rt, t, resolved, with_bot, helpf, nhelpf = db.execute(q).one()
    def f(x): return float(x or 0)
    resolve_rate = float(resolved or 0) / float(with_bot or 1)
    csat_rate = float(helpf or 0) / float(((helpf or 0) + (nhelpf or 0)) or 1)
    return {
        "avg_sessions": f(s),
        "avg_messages": f(m),
        "avg_response_ms": f(rt),
        "avg_turns": f(t),
        "resolve_rate_excluding_noresp": resolve_rate,
        "csat_rate": csat_rate,
    }
