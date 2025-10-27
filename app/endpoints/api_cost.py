# APP/api_cost.py
from __future__ import annotations
from datetime import date, datetime
from decimal import Decimal
from typing import List, Optional, Literal

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field, conint, condecimal
from sqlalchemy.orm import Session

from database.session import get_db
from crud import api_cost as crud
from schemas.api_cost import ApiCostDailyOut  # SCHEMAS/schemas_api_cost.py


router = APIRouter(prefix="/api-cost", tags=["Analytics"])


# ===== 요청/응답 스키마(엔드포인트 전용) =====
class AddEventRequest(BaseModel):
    ts_utc: datetime = Field(..., description="UTC 기준 호출 시각")
    product: str = Field(..., pattern="^(llm|embedding|stt|tts|image)$")
    model: str
    llm_tokens: conint(ge=0) = 0
    embedding_tokens: conint(ge=0) = 0
    audio_seconds: conint(ge=0) = 0
    cost_usd: condecimal(max_digits=12, decimal_places=6) = Decimal("0")


class EnsurePresentRequest(BaseModel):
    d: date
    product: str = Field(..., pattern="^(llm|embedding|stt|tts|image)$")
    model: str


class TotalsItem(BaseModel):
    d: Optional[date] = None
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


# ===== Add event (실시간 누적) =====
@router.post("/events")
def add_event(payload: AddEventRequest, db: Session = Depends(get_db)):
    crud.add_event(
        db,
        ts_utc=payload.ts_utc,
        product=payload.product,
        model=payload.model,
        llm_tokens=int(payload.llm_tokens),
        embedding_tokens=int(payload.embedding_tokens),
        audio_seconds=int(payload.audio_seconds),
        cost_usd=payload.cost_usd,
    )
    return {"ok": True}


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
