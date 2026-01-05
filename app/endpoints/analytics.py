# app/endpoints/analytics.py
from __future__ import annotations
from datetime import datetime, timezone, timedelta, date
from typing import Optional, List
from fastapi import APIRouter, Depends, Query, status, HTTPException
from sqlalchemy.orm import Session
from crud import daily_dashboard, analytics

from schemas.daily_dashboard import DailyDashboardResponse, WindowAveragesResponse, UpsertPayload
from database.session import get_db
from schemas.analytics import DashboardMetricsResponse, InquiryStats, DailyPoint, HourlyPoint, ModelStat
from service.metrics import recompute_model_metrics

router = APIRouter(prefix="/analytics", tags=["Analytics"])


# ISO8601 문자열을 datetime으로 변환(빈 값은 None 유지). 쿼리 파라미터 파싱용.
def _parse_dt(v: Optional[str]) -> Optional[datetime]:
    return datetime.fromisoformat(v) if v else None


# 기간 필터(ISO8601). 예: 2025-09-26T00:00:00
@router.get("/dashboard", response_model=DashboardMetricsResponse)
def dashboard_metrics(
    start: Optional[str] = Query(None, description="ISO8601:2025-09-26T00:00:00"),
    end: Optional[str] = Query(None, description="ISO8601"),
    db: Session = Depends(get_db),
):
    # 대시보드 핵심 지표 집계: 세션 수, 평균 응답(ms), 만족도, 문의 처리현황, 평균 턴수, 세션 해결률
    data = analytics.get_dashboard_metrics(db, start=_parse_dt(start), end=_parse_dt(end))
    return DashboardMetricsResponse(
        total_sessions=data["total_sessions"],
        avg_response_ms=data["avg_response_ms"],
        satisfaction_rate=data["satisfaction_rate"],
        inquiry=InquiryStats(**data["inquiry"]),
        avg_turns=data["avg_turns"],
        session_resolved_rate=data["session_resolved_rate"],
    )


# 일일 문의량
@router.get("/timeseries/daily", response_model=List[DailyPoint])
def daily_timeseries(
    # 최근 N일 기준 일별 시계열. 기본 30일, 최대 365일.
    days: int = Query(30, ge=1, le=365),
    db: Session = Depends(get_db)):

    # 날짜별 건수/지표 포인트 배열 반환(프론트 라인차트용)
    return [DailyPoint(**p) for p in analytics.get_daily_timeseries(db, days=days)]


@router.get("/timeseries/hourly", response_model=List[HourlyPoint])
def hourly_usage(
    # 최근 N일 합산 시간대별(0-23시) 사용량. 기본 7일, 최대 30일.
    days: int = Query(7, ge=1, le=30),
    db: Session = Depends(get_db)):

    # 시간대별 평균 또는 총합 포인트 배열 반환(히트맵/바차트용)
    return [HourlyPoint(**p) for p in analytics.get_hourly_usage(db, days=days)]


# 상위 N개 모델 성능/사용량 순위. 기본 10개, 최대 100개
@router.get("/models", response_model=List[ModelStat])
def model_stats(
    limit: int = Query(10, ge=1, le=100),
    db: Session = Depends(get_db),
):
    # 모델별 통계(정확도, 평균응답(ms), 월 대화량, 가동률 등) 반환
    return [ModelStat(**r) for r in analytics.get_model_stats(db, limit=limit)]



@router.post("/daily/upsert", status_code=status.HTTP_204_NO_CONTENT)
def upsert_daily(payload: UpsertPayload, db: Session = Depends(get_db)):
    daily_dashboard.upsert_daily_dashboard(db, start=payload.start, end=payload.end)
    return

@router.get("/daily", response_model=List[DailyDashboardResponse])
def get_daily(
    start: str = Query(..., description="YYYY-MM-DD (KST)"),
    end: str = Query(..., description="YYYY-MM-DD (KST)"),
    include_today: bool = Query(True),
    db: Session = Depends(get_db),
):
    s = date.fromisoformat(start)
    e = date.fromisoformat(end)
    items = daily_dashboard.list_daily(db, start=s, end=e, include_today=include_today)
    return [DailyDashboardResponse.model_validate(i) for i in items]

@router.get("/windows", response_model=WindowAveragesResponse)
def get_window(
    days: int = Query(30, ge=1, le=365),
    db: Session = Depends(get_db),
):
    data = daily_dashboard.window_averages(db, days=days)
    return WindowAveragesResponse(**data)

@router.post("/metrics/recompute")
def recompute(db: Session = Depends(get_db)):
    recompute_model_metrics(db)
    return {"ok": True}

