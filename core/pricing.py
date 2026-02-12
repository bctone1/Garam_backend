from __future__ import annotations
from decimal import Decimal, ROUND_HALF_UP
from typing import Optional, Iterable

import logging

from core import config

log = logging.getLogger("api_cost.pricing")

# tiktoken 사용 시도, 없으면 폴백
try:
    import tiktoken  # type: ignore
    _HAS_TIKTOKEN = True
except Exception:
    tiktoken = None  # type: ignore
    _HAS_TIKTOKEN = False


# === 공통 헬퍼 ===
def _quantize_usd(x: Decimal) -> Decimal:
    q = Decimal(10) ** -int(getattr(config, "COST_PRECISION", 6))
    return x.quantize(q, rounding=ROUND_HALF_UP)


def _require_price(product: str, model: str, key: str) -> Decimal:
    try:
        val = config.API_PRICING[product][model][key]
    except Exception as e:
        raise ValueError(f"pricing missing: {product}/{model}/{key}") from e
    return Decimal(str(val))


# ===== tiktoken 토큰 계산 유틸 =====
def _get_encoder_for_model(model: str):
    if not _HAS_TIKTOKEN:
        log.debug("tiktoken not installed. falling back to char-count for model=%s", model)
        return None
    try:
        return tiktoken.encoding_for_model(model)
    except Exception:
        try:
            return tiktoken.get_encoding("cl100k_base")
        except Exception:
            log.debug("tiktoken failed to get encoder, falling back to char-count for model=%s", model)
            return None


def tokens_for_text(model: str, text: str) -> int:
    """단일 문자열의 토큰 수 추정."""
    if not text:
        return 0
    enc = _get_encoder_for_model(model)
    if enc is None:
        return len(text)
    return len(enc.encode(text))


def tokens_for_texts(model: str, texts: Iterable[str]) -> int:
    """여러 텍스트 묶음의 총 토큰 수 추정."""
    enc = _get_encoder_for_model(model)
    if enc is None:
        return sum(len(t or "") for t in texts)
    total = 0
    for t in texts:
        total += len(enc.encode(t or ""))
    return total


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
    """
    토큰 수로 LLM 비용 계산. total_tokens 우선 사용.
    LLM_TOKEN_MODE이 'merged'면 prompt+completion 합산. 'separate'면 in/out 단가 활용 시 적용.
    """
    unit = Decimal(int(getattr(config, "TOKEN_UNIT", 1000)))
    mode = getattr(config, "LLM_TOKEN_MODE", "merged")

    if total_tokens is None:
        if mode == "merged":
            total_tokens = int(prompt_tokens) + int(completion_tokens)
        else:
            in_p = config.API_PRICING["llm"][model].get("per_1k_token_usd_in")
            out_p = config.API_PRICING["llm"][model].get("per_1k_token_usd_out")
            if in_p is not None and out_p is not None:
                usd = (Decimal(max(0, int(prompt_tokens))) / unit) * Decimal(str(in_p))
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



def estimate_whisper_stt(audio_seconds: float, model: str = "gpt-4o-mini-transcribe") -> Decimal:
    """OpenAI Whisper 계열 STT 비용: (seconds / 60) * per_minute_usd"""
    per_min = _require_price("stt", model, "per_minute_usd")
    usd = (Decimal(str(audio_seconds)) / Decimal("60")) * per_min
    return _quantize_usd(usd)
