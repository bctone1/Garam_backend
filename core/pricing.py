# CORE/pricing.py
from __future__ import annotations
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal, ROUND_HALF_UP
from math import ceil
from typing import List, Optional

from core import config


# === 공통 ===
def _quantize_usd(x: Decimal) -> Decimal:
    q = Decimal(10) ** -int(getattr(config, "COST_PRECISION", 6))
    return x.quantize(q, rounding=ROUND_HALF_UP)

def _require_price(product: str, model: str, key: str) -> Decimal:
    try:
        val = config.API_PRICING[product][model][key]
    except KeyError as e:
        raise ValueError(f"pricing missing: {product}/{model}/{key}") from e
    return Decimal(str(val))


# ===== 임베딩 =====
def _embedding_price_per_1k_usd(model: str) -> Decimal:
    return _require_price("embedding", model, "per_1k_token_usd")

def estimate_embedding_cost_usd(model: str, total_tokens: int) -> Decimal:
    tokens = max(0, int(total_tokens))
    per_1k = _embedding_price_per_1k_usd(model)
    unit = Decimal(int(getattr(config, "TOKEN_UNIT", 1000)))
    usd = (Decimal(tokens) / unit) * per_1k
    return _quantize_usd(usd)

def normalize_usage_embedding(total_tokens: int) -> dict:
    return {"llm_tokens": 0, "embedding_tokens": max(0, int(total_tokens)), "audio_seconds": 0}


# ===== LLM =====
def _llm_price_per_1k_usd(model: str) -> Decimal:
    return _require_price("llm", model, "per_1k_token_usd")

def estimate_llm_cost_usd(
    model: str,
    *,
    prompt_tokens: int = 0,
    completion_tokens: int = 0,
    total_tokens: Optional[int] = None,
) -> Decimal:
    unit = Decimal(int(getattr(config, "TOKEN_UNIT", 1000)))
    mode = getattr(config, "LLM_TOKEN_MODE", "merged")

    if total_tokens is None:
        if mode == "merged":
            total_tokens = int(prompt_tokens) + int(completion_tokens)
        else:
            in_p  = config.API_PRICING["llm"][model].get("per_1k_token_usd_in")
            out_p = config.API_PRICING["llm"][model].get("per_1k_token_usd_out")
            if in_p is not None and out_p is not None:
                usd = (Decimal(max(0, int(prompt_tokens)))   / unit) * Decimal(str(in_p))
                usd += (Decimal(max(0, int(completion_tokens))) / unit) * Decimal(str(out_p))
                return _quantize_usd(usd)
            total_tokens = int(prompt_tokens) + int(completion_tokens)

    tokens = max(0, int(total_tokens))
    per_1k = _llm_price_per_1k_usd(model)
    usd = (Decimal(tokens) / unit) * per_1k
    return _quantize_usd(usd)

def normalize_usage_llm(
    *,
    prompt_tokens: int = 0,
    completion_tokens: int = 0,
    total_tokens: Optional[int] = None,
) -> dict:
    if total_tokens is None:
        total_tokens = int(prompt_tokens) + int(completion_tokens)
    return {"llm_tokens": max(0, int(total_tokens)), "embedding_tokens": 0, "audio_seconds": 0}


# ===== CLOVA STT 사용량 이벤트/요약 =====
# 클로바가 직접제공하는 api 함수가 없어서 내부 계산값 간단히 정의 위해 @ 객체 정의 사용
@dataclass
class ClovaSttUsageEvent:
    mode: str                               # "short_sync" | "live_grpc" 등
    audio_seconds: float = 0.0
    started_at: Optional[datetime] = None
    ended_at: Optional[datetime] = None
    meta: Optional[dict] = None

@dataclass
class ClovaSttUsageSummary:
    raw_seconds: float
    bill_seconds: int
    price_krw: int
    price_usd: Optional[Decimal] = None


# ===== STT 내부 헬퍼 =====
def _effective_seconds(e: ClovaSttUsageEvent) -> float:
    if e.audio_seconds and e.audio_seconds > 0:
        return float(e.audio_seconds)
    if e.started_at and e.ended_at:
        return max(0.0, (e.ended_at - e.started_at).total_seconds())
    return 0.0

def _billable_seconds(seconds: float) -> int:
    unit = int(getattr(config, "CLOVA_STT_BILLING_UNIT_SECONDS", 15))
    if seconds <= 0:
        return 0
    return int(ceil(seconds / unit) * unit)

def _price_krw_for_bill_seconds(bill_secs: int) -> int:
    unit = int(getattr(config, "CLOVA_STT_BILLING_UNIT_SECONDS", 15))
    per_unit_krw = int(getattr(config, "CLOVA_STT_PRICE_PER_UNIT_KRW", 0))
    units = bill_secs // unit
    return int(units * per_unit_krw)

def _krw_to_usd(krw: int) -> Optional[Decimal]:
    fx = getattr(config, "FX_KRW_PER_USD", None)
    if not fx:
        return None
    q = Decimal(10) ** -int(getattr(config, "COST_PRECISION", 6))
    return (Decimal(int(krw)) / Decimal(str(fx))).quantize(q, rounding=ROUND_HALF_UP)


# ===== STT 공개 API =====
def estimate_clova_stt(events: List[ClovaSttUsageEvent]) -> ClovaSttUsageSummary:
    total_raw = 0.0
    total_bill = 0
    total_price = 0

    for e in events:
        secs = _effective_seconds(e)
        total_raw += secs
        bsecs = _billable_seconds(secs)
        total_bill += bsecs
        total_price += _price_krw_for_bill_seconds(bsecs)

    total_raw = round(total_raw, 2)
    usd = _krw_to_usd(total_price)
    return ClovaSttUsageSummary(
        raw_seconds=total_raw,
        bill_seconds=total_bill,
        price_krw=int(total_price),
        price_usd=usd,
    )

def normalize_usage_stt(raw_seconds: float) -> dict:
    bsecs = _billable_seconds(raw_seconds)
    return {"llm_tokens": 0, "embedding_tokens": 0, "audio_seconds": int(bsecs)}