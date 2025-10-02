# service/metrics.py
from sqlalchemy import text
from sqlalchemy.orm import Session
from crud import model as crud_model

def recompute_model_metrics(db: Session) -> None:
    avg_ms = db.execute(text("""
        SELECT COALESCE(AVG(response_latency_ms), 0)
        FROM message
        WHERE role='assistant' AND created_at >= date_trunc('month', now())
    """)).scalar() or 0

    month_convs = db.execute(text("""
        SELECT COUNT(*) FROM chat_session
        WHERE created_at >= date_trunc('month', now())
    """)).scalar() or 0

    accuracy = db.execute(text("""
        SELECT COALESCE(
          AVG(
            CASE
              WHEN rating ~ '^[0-9]+(\\.[0-9]+)?$' AND rating::numeric >= 4 THEN 1
              WHEN rating ILIKE 'helpful' THEN 1
              WHEN rating ILIKE 'unhelpful' THEN 0
              ELSE NULL
            END
          ) * 100, 0
        )
        FROM feedback
        WHERE created_at >= date_trunc('month', now())
    """)).scalar() or 0

    uptime = db.execute(text("""
        SELECT COALESCE(
          (COUNT(*) FILTER (WHERE (extra_data->>'error') IS NULL))::float
          / NULLIF(COUNT(*),0) * 100, 100
        )
        FROM message
        WHERE role='assistant' AND created_at >= date_trunc('month', now())
    """)).scalar() or 100

    crud_model.update_metrics(
        db,
        model_id=1,
        accuracy=float(accuracy),
        avg_response_time_ms=int(avg_ms),
        month_conversations=int(month_convs),
        uptime_percent=float(uptime),
    )
