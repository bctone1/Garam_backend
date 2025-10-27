# crud/api_cost.py
from __future__ import annotations
from datetime import date, datetime, timezone, timedelta
from decimal import Decimal
from typing import Optional, Literal

from sqlalchemy import select, func, text
from sqlalchemy.orm import Session

from models.api_cost import ApiCostDaily


# ===== KST 날짜 도우미 =====
_KST_OFFSET = 9 * 3600

def _to_kst_date(ts_utc: datetime) -> date:
    if ts_utc.tzinfo is None:
        ts_utc = ts_utc.replace(tzinfo=timezone.utc)
    return (ts_utc + timedelta(seconds=_KST_OFFSET)).date()


# ===== 기본 조회 =====
def get(db: Session, d: date, product: str, model: str) -> Optional[ApiCostDaily]:
    return (
        db.query(ApiCostDaily)
        .filter_by(d=d, product=product, model=model)
        .one_or_none()
    )

def list_range(
    db: Session,
    start: date,
    end: date,
    product: Optional[str] = None,
    model: Optional[str] = None,
) -> list[ApiCostDaily]:
    q = db.query(ApiCostDaily).filter(ApiCostDaily.d.between(start, end))
    if product:
        q = q.filter(ApiCostDaily.product == product)
    if model:
        q = q.filter(ApiCostDaily.model == model)
    return q.order_by(ApiCostDaily.d.asc(), ApiCostDaily.product.asc(), ApiCostDaily.model.asc()).all()


# ===== 실시간 upsert (누적) =====
def upsert_add(
    db: Session,
    *,
    d: date,
    product: str,
    model: str,
    llm_tokens: int = 0,
    embedding_tokens: int = 0,
    audio_seconds: int = 0,
    cost_usd: Decimal | float = 0,
) -> None:
    sql = text(
        """
        INSERT INTO api_cost_daily
        (d, product, model, llm_tokens, embedding_tokens, audio_seconds, cost_usd)
        VALUES (:d, :product, :model, :llm_tokens, :embedding_tokens, :audio_seconds, :cost_usd)
        ON CONFLICT (d, product, model) DO UPDATE SET
            llm_tokens       = api_cost_daily.llm_tokens       + EXCLUDED.llm_tokens,
            embedding_tokens = api_cost_daily.embedding_tokens + EXCLUDED.embedding_tokens,
            audio_seconds    = api_cost_daily.audio_seconds    + EXCLUDED.audio_seconds,
            cost_usd         = api_cost_daily.cost_usd         + EXCLUDED.cost_usd,
            updated_at       = now()
        """
    )
    db.execute(
        sql,
        dict(
            d=d,
            product=product,
            model=model,
            llm_tokens=int(llm_tokens),
            embedding_tokens=int(embedding_tokens),
            audio_seconds=int(audio_seconds),
            cost_usd=Decimal(str(cost_usd)),
        ),
    )
    db.commit()


# ===== 절대값 덮어쓰기 =====
def upsert_set(
    db: Session,
    *,
    d: date,
    product: str,
    model: str,
    llm_tokens: int = 0,
    embedding_tokens: int = 0,
    audio_seconds: int = 0,
    cost_usd: Decimal | float = 0,
) -> None:
    sql = text(
        """
        INSERT INTO api_cost_daily
        (d, product, model, llm_tokens, embedding_tokens, audio_seconds, cost_usd)
        VALUES (:d, :product, :model, :llm_tokens, :embedding_tokens, :audio_seconds, :cost_usd)
        ON CONFLICT (d, product, model) DO UPDATE SET
            llm_tokens       = :llm_tokens,
            embedding_tokens = :embedding_tokens,
            audio_seconds    = :audio_seconds,
            cost_usd         = :cost_usd,
            updated_at       = now()
        """
    )
    db.execute(
        sql,
        dict(
            d=d,
            product=product,
            model=model,
            llm_tokens=int(llm_tokens),
            embedding_tokens=int(embedding_tokens),
            audio_seconds=int(audio_seconds),
            cost_usd=Decimal(str(cost_usd)),
        ),
    )
    db.commit()


# ===== 스케줄러 보조: 존재 보장(0행 생성) =====
def ensure_present(db: Session, d: date, product: str, model: str) -> None:
    sql = text(
        """
        INSERT INTO api_cost_daily
        (d, product, model, llm_tokens, embedding_tokens, audio_seconds, cost_usd)
        VALUES (:d, :product, :model, 0, 0, 0, 0)
        ON CONFLICT (d, product, model) DO NOTHING
        """
    )
    db.execute(sql, dict(d=d, product=product, model=model))
    db.commit()


# ===== 이벤트 훅(실시간 경로에서 호출) =====
def add_event(
    db: Session,
    *,
    ts_utc: datetime,
    product: str,
    model: str,
    llm_tokens: int = 0,
    embedding_tokens: int = 0,
    audio_seconds: int = 0,
    cost_usd: Decimal | float = 0,
) -> None:
    d = _to_kst_date(ts_utc)
    upsert_add(
        db,
        d=d,
        product=product,
        model=model,
        llm_tokens=llm_tokens,
        embedding_tokens=embedding_tokens,
        audio_seconds=audio_seconds,
        cost_usd=cost_usd,
    )


# ===== 합계 =====
def totals(
    db: Session,
    start: date,
    end: date,
    group: Literal["none", "product", "product_model", "day", "day_product"] = "none",
):
    base = select(
        ApiCostDaily.d,
        ApiCostDaily.product,
        ApiCostDaily.model,
        func.sum(ApiCostDaily.llm_tokens).label("llm_tokens"),
        func.sum(ApiCostDaily.embedding_tokens).label("embedding_tokens"),
        func.sum(ApiCostDaily.audio_seconds).label("audio_seconds"),
        func.sum(ApiCostDaily.cost_usd).label("cost_usd"),
    ).where(ApiCostDaily.d.between(start, end))

    if group == "none":
        s = select(
            func.sum(ApiCostDaily.llm_tokens),
            func.sum(ApiCostDaily.embedding_tokens),
            func.sum(ApiCostDaily.audio_seconds),
            func.sum(ApiCostDaily.cost_usd),
        ).where(ApiCostDaily.d.between(start, end))
        r = db.execute(s).one()
        return [
            dict(
                llm_tokens=r[0] or 0,
                embedding_tokens=r[1] or 0,
                audio_seconds=r[2] or 0,
                cost_usd=r[3] or 0,
            )
        ]

    groups = {
        "product": [ApiCostDaily.product],
        "product_model": [ApiCostDaily.product, ApiCostDaily.model],
        "day": [ApiCostDaily.d],
        "day_product": [ApiCostDaily.d, ApiCostDaily.product],
    }[group]

    s = base.group_by(*groups).order_by(*groups)
    return [dict(row._mapping) for row in db.execute(s).all()]


# ===== 삭제 =====
def delete_range(
    db: Session,
    start: date,
    end: date,
    product: Optional[str] = None,
    model: Optional[str] = None,
) -> int:
    q = db.query(ApiCostDaily).filter(ApiCostDaily.d.between(start, end))
    if product:
        q = q.filter(ApiCostDaily.product == product)
    if model:
        q = q.filter(ApiCostDaily.model == model)
    n = q.delete(synchronize_session=False)
    db.commit()
    return n
