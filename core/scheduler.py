from __future__ import annotations
from datetime import date, datetime, timedelta
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

_SCHED: AsyncIOScheduler | None = None  # <<< 전역 스케줄러 참조

def _kst_now() -> datetime:
    return datetime.now(TZ)

def _kst_today() -> date:
    return _kst_now().date()

def _run_upsert_for(day: date):
    db: Session = SessionLocal()
    try:
        crud.upsert_daily_dashboard(db, start=day, end=day)
        log.info("daily_dashboard upserted for %s", day.isoformat())
    except Exception:
        log.exception("upsert failed for %s", day)
    finally:
        db.close()

def job_prev_day():
    # 매일 00:05 KST → 전일 집계
    _run_upsert_for(_kst_today() - timedelta(days=1))

def job_today_hourly():
    # 매시간 05분 KST → 당일 갱신(준실시간)
    _run_upsert_for(_kst_today())

def init_scheduler(start_immediately: bool = True) -> AsyncIOScheduler:
    global _SCHED
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

    if start_immediately:
        # 부팅 직후 보정: 전일/당일 한 번씩 빠르게 실행
        run_at = _kst_now() + timedelta(seconds=5)
        sched.add_job(job_prev_day, trigger="date", run_date=run_at,
                      id="boot_prev_day", replace_existing=True)
        sched.add_job(job_today_hourly, trigger="date", run_date=run_at + timedelta(seconds=5),
                      id="boot_today", replace_existing=True)

    _SCHED = sched
    return sched

# ========= 외부에서 호출하는 "이벤트 트리거"들 =========

def trigger_upsert_today_now():
    """챗 메시지(특히 assistant) 생성 직후 즉시 당일만 리컴퓨트."""
    if _SCHED and _SCHED.running:
        _SCHED.add_job(_run_upsert_for, trigger="date", run_date=_kst_now(),
                       args=[_kst_today()],
                       id=f"adhoc_today_{_kst_now().timestamp()}")
    else:
        # 스케줄러가 아직 없으면 동기로 실행 (fallback)
        _run_upsert_for(_kst_today())

def trigger_upsert_for(day: date):
    """임의 날짜 하루만 재집계(관리자 버튼/엔드포인트 등)."""
    if _SCHED and _SCHED.running:
        _SCHED.add_job(_run_upsert_for, trigger="date", run_date=_kst_now(),
                       args=[day],
                       id=f"adhoc_{day.isoformat()}_{_kst_now().timestamp()}")
    else:
        _run_upsert_for(day)

def trigger_upsert_range(start: date, end: date):
    """구간 재집계(백필). 날짜별로 1초 간격으로 순차 등록."""
    cur = start
    offset = 0
    while cur <= end:
        run_at = _kst_now() + timedelta(seconds=offset)
        if _SCHED and _SCHED.running:
            _SCHED.add_job(_run_upsert_for, trigger="date", run_date=run_at,
                           args=[cur],
                           id=f"adhoc_{cur.isoformat()}")
        else:
            _run_upsert_for(cur)
        cur += timedelta(days=1)
        offset += 1


# ========= 공지사항 푸시 스케줄링 =========

def _notice_push_job_id(notice_id: int) -> str:
    return f"notice_push_{notice_id}"


def schedule_notice_push(notice_id: int, run_at: datetime) -> None:
    """예약 게시일 도달 시 푸시 발송. 이미 등록된 잡이 있으면 교체."""
    from services.notice_push import push_notice
    if _SCHED and _SCHED.running:
        _SCHED.add_job(
            push_notice,
            trigger="date",
            run_date=run_at,
            args=[notice_id],
            id=_notice_push_job_id(notice_id),
            replace_existing=True,
            misfire_grace_time=600,
        )
        log.info("notice push 스케줄 등록: notice_id=%s, run_at=%s", notice_id, run_at)
    else:
        # 스케줄러 미가동 — 즉시 동기 실행 fallback
        push_notice(notice_id)


def cancel_notice_push(notice_id: int) -> None:
    """예약된 푸시 취소(공지 수정/삭제 시)."""
    if not _SCHED:
        return
    try:
        _SCHED.remove_job(_notice_push_job_id(notice_id))
        log.info("notice push 스케줄 취소: notice_id=%s", notice_id)
    except Exception:
        # 잡이 없거나 이미 실행됨 — 무시
        pass


def push_notice_now(notice_id: int) -> None:
    """즉시 발송(또는 스케줄러에 즉시 등록)."""
    from services.notice_push import push_notice
    if _SCHED and _SCHED.running:
        _SCHED.add_job(
            push_notice,
            trigger="date",
            run_date=_kst_now() + timedelta(seconds=1),
            args=[notice_id],
            id=f"notice_push_now_{notice_id}_{_kst_now().timestamp()}",
        )
    else:
        push_notice(notice_id)
