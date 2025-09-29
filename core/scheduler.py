from __future__ import annotations
from datetime import timedelta
from zoneinfo import ZoneInfo
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from sqlalchemy.orm import Session
import logging

from database.session import SessionLocal
from crud import daily_dashboard as crud


### 전일: 매일 00:05 KST 자동 집계.
### 당일: 매시간 05분 갱신.


TZ = ZoneInfo("Asia/Seoul")
log = logging.getLogger("scheduler")

def _kst_today():
    from datetime import datetime
    return datetime.now(TZ).date()

def _run_upsert_for(day):
    db: Session = SessionLocal()
    try:
        crud.upsert_daily_dashboard(db, start=day, end=day)
        log.info("daily_dashboard upserted for %s", day.isoformat())
    except Exception as e:
        log.exception("upsert failed for %s: %s", day, e)
    finally:
        db.close()

def job_prev_day():
    # 매일 00:05 KST → 전일 집계
    today = _kst_today()
    _run_upsert_for(today - timedelta(days=1))

def job_today_hourly():
    # 매시간 05분 KST → 당일 갱신(준실시간)
    today = _kst_today()
    _run_upsert_for(today)

def init_scheduler():
    sched = AsyncIOScheduler(
        timezone=TZ,
        job_defaults={"coalesce": True, "max_instances": 1},
    )
    # 전일 집계: 매일 00:05
    sched.add_job(job_prev_day, trigger="cron", hour=0, minute=5,
                  id="daily_dashboard_prev_day", replace_existing=True, misfire_grace_time=600)
    # 당일 갱신: 매시간 05분
    sched.add_job(job_today_hourly, trigger="cron", minute=5,
                  id="daily_dashboard_today_hourly", replace_existing=True, misfire_grace_time=300)
    return sched
