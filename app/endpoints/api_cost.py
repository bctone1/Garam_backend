# APP/api_cost.py
from __future__ import annotations
from datetime import date, datetime
from decimal import Decimal
from typing import List, Optional, Literal, Dict

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field, conint, condecimal
from sqlalchemy.orm import Session

from database.session import get_db
from crud import api_cost as crud
from schemas.api_cost import ApiCostDailyOut

# 대시보드 비용 넣을때 사용
from core.pricing import (
    estimate_llm_cost_usd,
    estimate_embedding_cost_usd,
    estimate_clova_stt,
    ClovaSttUsageEvent,
    normalize_usage_stt,
)

router = APIRouter(prefix="/api-cost", tags=["Analytics"])


# ===== 요청/응답 스키마 =====
class AddEventRequest(BaseModel):
    ts_utc: datetime = Field(..., description="UTC 기준 호출 시각")
    product: str = Field(..., pattern="^(llm|embedding|stt)$")
    model: str

    # 사용량(사후)
    llm_tokens: conint(ge=0) = 0
    embedding_tokens: conint(ge=0) = 0
    audio_seconds: conint(ge=0) = 0

    # 선택: 외부 정산값을 그대로 씀(>0일 때)
    cost_usd: condecimal(max_digits=12, decimal_places=6) = Decimal("0")


class EnsurePresentRequest(BaseModel):
    date: date
    product: str = Field(..., pattern="^(llm|embedding|stt)$")
    model: str


class TotalsItem(BaseModel):
    date: Optional[date] = None
    product: Optional[str] = None
    model: Optional[str] = None
    llm_tokens: int
    embedding_tokens: int
    audio_seconds: int
    cost_usd: Decimal


# ===== Rows =====
@router.get("/rows", response_model=List[ApiCostDailyOut])
def list_rows(
    start: date = Query(...),
    end: date = Query(...),
    product: Optional[str] = Query(None),
    model: Optional[str] = Query(None),
    db: Session = Depends(get_db),
):
    return crud.list_range(db, start=start, end=end, product=product, model=model)


# ===== Totals =====
@router.get("/totals", response_model=List[TotalsItem])
def get_totals(
    start: date = Query(...),
    end: date = Query(...),
    group: Literal["none", "product", "product_model", "day", "day_product"] = Query("none"),
    db: Session = Depends(get_db),
):
    return crud.totals(db, start=start, end=end, group=group)


# ===== Timeseries (차트용) =====
@router.get("/timeseries", response_model=List[TotalsItem])
def get_timeseries(
    start: date = Query(...),
    end: date = Query(...),
    product: Optional[str] = Query(None),
    model: Optional[str] = Query(None),
    db: Session = Depends(get_db),
):
    rows = crud.list_range(db, start=start, end=end, product=product, model=model)
    agg: Dict[date, Dict[str, Decimal | int]] = {}
    for r in rows:
        k = r.date
        if k not in agg:
            agg[k] = dict(llm_tokens=0, embedding_tokens=0, audio_seconds=0, cost_usd=Decimal("0"))
        agg[k]["llm_tokens"] += int(r.llm_tokens or 0)
        agg[k]["embedding_tokens"] += int(r.embedding_tokens or 0)
        agg[k]["audio_seconds"] += int(r.audio_seconds or 0)
        agg[k]["cost_usd"] += Decimal(str(r.cost_usd or 0))
    out: List[TotalsItem] = []
    for d_key in sorted(agg.keys()):
        v = agg[d_key]
        out.append(
            TotalsItem(
                date=d_key,
                product=None,
                model=None,
                llm_tokens=int(v["llm_tokens"]),
                embedding_tokens=int(v["embedding_tokens"]),
                audio_seconds=int(v["audio_seconds"]),
                cost_usd=Decimal(v["cost_usd"]),
            )
        )
    return out


# ===== Add event (실시간 누적, 서버 계산 기본) =====
@router.post("/events")
def add_event(payload: AddEventRequest, db: Session = Depends(get_db)):

    # 비용 산정: override가 0이면 서버 계산
    cost_usd: Decimal = Decimal(payload.cost_usd)

    if cost_usd <= 0:
        if payload.product == "llm":
            cost_usd = estimate_llm_cost_usd(
                payload.model,
                total_tokens=int(payload.llm_tokens),
            )
        elif payload.product == "embedding":
            cost_usd = estimate_embedding_cost_usd(
                payload.model,
                total_tokens=int(payload.embedding_tokens),
            )
        elif payload.product == "stt":
            # STT는 원화 규칙 기반 → USD 환산 설정이 없으면 0일 수 있음
            ev = ClovaSttUsageEvent(mode="api", audio_seconds=float(payload.audio_seconds))
            summary = estimate_clova_stt([ev])
            cost_usd = summary.price_usd or Decimal("0")
            # billable seconds로 치환
            payload.audio_seconds = normalize_usage_stt(summary.raw_seconds)["audio_seconds"]

    crud.add_event(
        db,
        ts_utc=payload.ts_utc,
        product=payload.product,
        model=payload.model,
        llm_tokens=int(payload.llm_tokens),
        embedding_tokens=int(payload.embedding_tokens),
        audio_seconds=int(payload.audio_seconds),
        cost_usd=cost_usd,
    )
    return {"ok": True, "cost_usd": str(cost_usd)}


# ===== Ensure row present (스케줄러 보조) =====
@router.post("/ensure")
def ensure_row(payload: EnsurePresentRequest, db: Session = Depends(get_db)):
    crud.ensure_present(db, d=payload.d, product=payload.product, model=payload.model)
    return {"ok": True}


# ===== Admin: 삭제 =====
@router.delete("/rows")
def delete_rows(
    start: date = Query(...),
    end: date = Query(...),
    product: Optional[str] = Query(None),
    model: Optional[str] = Query(None),
    db: Session = Depends(get_db),
):
    n = crud.delete_range(db, start=start, end=end, product=product, model=model)
    return {"deleted": n}
