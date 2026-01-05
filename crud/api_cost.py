# crud/api_cost.py
from __future__ import annotations

from datetime import date, datetime, timezone, timedelta
from decimal import Decimal
from typing import Optional, Literal, Any

from sqlalchemy import select, func, text
from sqlalchemy.orm import Session

from models.api_cost import ApiCostDaily

# ===== KST 날짜 도우미 =====
_KST = timezone(timedelta(hours=9))


def _to_utc(ts: datetime) -> datetime:
    if ts.tzinfo is None:
        return ts.replace(tzinfo=timezone.utc)
    return ts.astimezone(timezone.utc)


def _to_kst_date(ts_utc: datetime) -> date:
    """
    이벤트 기준 ts(UTC or tz-aware)를 KST 날짜로 변환.
    """
    ts_utc = _to_utc(ts_utc)
    return ts_utc.astimezone(_KST).date()


def _d_today_kst() -> date:
    return datetime.now(timezone.utc).astimezone(_KST).date()


def _as_decimal(v: Decimal | float | int | str) -> Decimal:
    return v if isinstance(v, Decimal) else Decimal(str(v))


# ===== 기본 조회 =====
def get(db: Session, *, d: date, product: str, model: str) -> Optional[ApiCostDaily]:
    stmt = select(ApiCostDaily).where(
        ApiCostDaily.d == d,
        ApiCostDaily.product == product,
        ApiCostDaily.model == model,
    )
    return db.scalars(stmt).first()


def list_range(
    db: Session,
    *,
    start: date,
    end: date,
    product: Optional[str] = None,
    model: Optional[str] = None,
    offset: int = 0,
    limit: int = 500,
) -> list[ApiCostDaily]:
    stmt = select(ApiCostDaily).where(ApiCostDaily.d.between(start, end))
    if product:
        stmt = stmt.where(ApiCostDaily.product == product)
    if model:
        stmt = stmt.where(ApiCostDaily.model == model)

    stmt = (
        stmt.order_by(ApiCostDaily.d.asc(), ApiCostDaily.product.asc(), ApiCostDaily.model.asc())
        .offset(offset)
        .limit(min(limit, 2000))
    )
    return list(db.scalars(stmt).all())


# ===== upsert(누적) / upsert(덮어쓰기) =====
_UPSERT_ADD_SQL = text(
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

_UPSERT_SET_SQL = text(
    """
    INSERT INTO api_cost_daily
    (d, product, model, llm_tokens, embedding_tokens, audio_seconds, cost_usd)
    VALUES (:d, :product, :model, :llm_tokens, :embedding_tokens, :audio_seconds, :cost_usd)
    ON CONFLICT (d, product, model) DO UPDATE SET
        llm_tokens       = EXCLUDED.llm_tokens,
        embedding_tokens = EXCLUDED.embedding_tokens,
        audio_seconds    = EXCLUDED.audio_seconds,
        cost_usd         = EXCLUDED.cost_usd,
        updated_at       = now()
    """
)

_ENSURE_PRESENT_SQL = text(
    """
    INSERT INTO api_cost_daily
    (d, product, model, llm_tokens, embedding_tokens, audio_seconds, cost_usd)
    VALUES (:d, :product, :model, 0, 0, 0, 0)
    ON CONFLICT (d, product, model) DO NOTHING
    """
)


def upsert_add(
    db: Session,
    *,
    d: date,
    product: str,
    model: str,
    llm_tokens: int = 0,
    embedding_tokens: int = 0,
    audio_seconds: int = 0,
    cost_usd: Decimal | float | int | str = 0,
    commit: bool = True,
) -> None:
    db.execute(
        _UPSERT_ADD_SQL,
        dict(
            d=d,
            product=product,
            model=model,
            llm_tokens=int(llm_tokens or 0),
            embedding_tokens=int(embedding_tokens or 0),
            audio_seconds=int(audio_seconds or 0),
            cost_usd=_as_decimal(cost_usd or 0),
        ),
    )
    if commit:
        db.commit()
    else:
        db.flush()


def upsert_set(
    db: Session,
    *,
    d: date,
    product: str,
    model: str,
    llm_tokens: int = 0,
    embedding_tokens: int = 0,
    audio_seconds: int = 0,
    cost_usd: Decimal | float | int | str = 0,
    commit: bool = True,
) -> None:
    db.execute(
        _UPSERT_SET_SQL,
        dict(
            d=d,
            product=product,
            model=model,
            llm_tokens=int(llm_tokens or 0),
            embedding_tokens=int(embedding_tokens or 0),
            audio_seconds=int(audio_seconds or 0),
            cost_usd=_as_decimal(cost_usd or 0),
        ),
    )
    if commit:
        db.commit()
    else:
        db.flush()


def ensure_present(
    db: Session,
    *,
    d: date,
    product: str,
    model: str,
    commit: bool = True,
) -> None:
    db.execute(_ENSURE_PRESENT_SQL, dict(d=d, product=product, model=model))
    if commit:
        db.commit()
    else:
        db.flush()


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
    cost_usd: Decimal | float | int | str = 0,
    commit: bool = True,
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
        commit=commit,
    )


# ===== 합계 =====
GroupLiteral = Literal["none", "product", "product_model", "day", "day_product"]


def totals(
    db: Session,
    *,
    start: date,
    end: date,
    group: GroupLiteral = "none",
) -> list[dict[str, Any]]:
    """
    기간 합계 조회.
    group:
      - none: 단일 합계
      - product: product별
      - product_model: product+model별
      - day: 일자별
      - day_product: 일자+product별
    """
    if group == "none":
        s = select(
            func.coalesce(func.sum(ApiCostDaily.llm_tokens), 0).label("llm_tokens"),
            func.coalesce(func.sum(ApiCostDaily.embedding_tokens), 0).label("embedding_tokens"),
            func.coalesce(func.sum(ApiCostDaily.audio_seconds), 0).label("audio_seconds"),
            func.coalesce(func.sum(ApiCostDaily.cost_usd), 0).label("cost_usd"),
        ).where(ApiCostDaily.d.between(start, end))
        r = db.execute(s).one()
        return [
            dict(
                llm_tokens=int(r.llm_tokens),
                embedding_tokens=int(r.embedding_tokens),
                audio_seconds=int(r.audio_seconds),
                cost_usd=r.cost_usd,
            )
        ]

    groups_map = {
        "product": [ApiCostDaily.product],
        "product_model": [ApiCostDaily.product, ApiCostDaily.model],
        "day": [ApiCostDaily.d],
        "day_product": [ApiCostDaily.d, ApiCostDaily.product],
    }
    cols = groups_map[group]

    base = (
        select(
            ApiCostDaily.d,
            ApiCostDaily.product,
            ApiCostDaily.model,
            func.coalesce(func.sum(ApiCostDaily.llm_tokens), 0).label("llm_tokens"),
            func.coalesce(func.sum(ApiCostDaily.embedding_tokens), 0).label("embedding_tokens"),
            func.coalesce(func.sum(ApiCostDaily.audio_seconds), 0).label("audio_seconds"),
            func.coalesce(func.sum(ApiCostDaily.cost_usd), 0).label("cost_usd"),
        )
        .where(ApiCostDaily.d.between(start, end))
        .group_by(*cols)
        .order_by(*cols)
    )

    rows = db.execute(base).all()
    return [dict(row._mapping) for row in rows]


# ===== 삭제 =====
def delete_range(
    db: Session,
    *,
    start: date,
    end: date,
    product: Optional[str] = None,
    model: Optional[str] = None,
    commit: bool = True,
) -> int:
    stmt = select(ApiCostDaily).where(ApiCostDaily.d.between(start, end))
    if product:
        stmt = stmt.where(ApiCostDaily.product == product)
    if model:
        stmt = stmt.where(ApiCostDaily.model == model)

    rows = list(db.scalars(stmt).all())
    n = len(rows)
    for r in rows:
        db.delete(r)

    if commit:
        db.commit()
    else:
        db.flush()
    return n
