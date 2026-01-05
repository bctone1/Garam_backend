# service/llm_service.py
from __future__ import annotations

import logging
import time
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any, Dict, List, Literal, Optional, Union

from fastapi import HTTPException, status
from fastapi.encoders import jsonable_encoder
from sqlalchemy.orm import Session

from core import config
from core.pricing import ClovaSttUsageEvent, estimate_clova_stt, normalize_usage_stt
from crud import api_cost as crud_cost
from crud import chat as crud_chat
from langchain_service.llm.runner import _run_qa
from schemas.llm import ChatQARequest, QAResponse, STTResponse
from service.stt import (
    clova_transcribe,
    ensure_wav_16k_mono,
    probe_duration_seconds,
    wav_duration_seconds,
)

log = logging.getLogger("api_cost")


def _ensure_session(db: Session, session_id: int) -> None:
    if not crud_chat.get_session(db, session_id):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="session not found")


def _extract_policy_flags(obj: Any) -> dict:
    flags: dict = {}
    for k in ("block_inappropriate", "restrict_non_tech", "suggest_agent_handoff"):
        v = getattr(obj, k, None)
        if v is not None:
            flags[k] = v
    return flags


def _dump_sources(resp: QAResponse) -> list[dict]:
    out: list[dict] = []
    for s in (getattr(resp, "sources", None) or []):
        if hasattr(s, "model_dump"):
            out.append(s.model_dump())
        else:
            out.append(jsonable_encoder(s))
    return out


def ask_in_session_service(db: Session, *, session_id: int, payload: ChatQARequest) -> QAResponse:
    _ensure_session(db, session_id)

    if getattr(payload, "role", "user") != "user":
        raise HTTPException(status_code=400, detail="role must be 'user'")

    flags = _extract_policy_flags(payload)
    few_shot_profile: str = str(getattr(payload, "few_shot_profile", None) or "support_md")

    # user message 기록
    crud_chat.create_message(
        db,
        session_id=session_id,
        role="user",
        content=payload.question,
        vector_memory=None,
        response_latency_ms=None,
        extra_data={
            "knowledge_id": payload.knowledge_id,
            "top_k": payload.top_k,
            "style": payload.style,
            "policy_flags": flags,
            "few_shot_profile": few_shot_profile,
            "source": "text",
        },
    )

    t0 = time.perf_counter()
    resp = _run_qa(
        db,
        question=payload.question,
        knowledge_id=payload.knowledge_id,
        top_k=payload.top_k,
        session_id=session_id,
        policy_flags=flags,
        style=payload.style,
        few_shot_profile=few_shot_profile,
    )
    latency_ms = int((time.perf_counter() - t0) * 1000)

    if resp is None:
        raise HTTPException(status_code=502, detail="_run_qa returned None")

    # assistant message 기록
    crud_chat.create_message(
        db,
        session_id=session_id,
        role="assistant",
        content=resp.answer,
        vector_memory=None,
        response_latency_ms=latency_ms,
        extra_data=jsonable_encoder(
            {
                "knowledge_id": payload.knowledge_id,
                "top_k": payload.top_k,
                "style": payload.style,
                "policy_flags": flags,
                "few_shot_profile": few_shot_profile,
                "sources": _dump_sources(resp),
                "source": "text",
            }
        ),
    )
    return resp


def clova_stt_service(
    db: Session,
    *,
    raw: bytes,
    content_type: str,
    lang: str,
    knowledge_id: Optional[int],
    top_k: int,
    session_id: Optional[int],
    style: Optional[str],
    block_inappropriate: Optional[bool],
    restrict_non_tech: Optional[bool],
    suggest_agent_handoff: Optional[bool],
    few_shot_profile: str,
) -> Union[STTResponse, QAResponse]:
    wav = ensure_wav_16k_mono(raw, content_type)

    # 1) STT
    text = clova_transcribe(wav, lang).strip()
    if not text:
        raise HTTPException(status_code=422, detail="empty transcription")

    # 2) 길이 산출 → 비용 기록
    secs = wav_duration_seconds(wav)
    if secs <= 0:
        secs = probe_duration_seconds(raw)
    if secs <= 0:
        log.warning("STT duration fallback to 6s (default)")
        secs = 6.0

    try:
        summary = estimate_clova_stt([ClovaSttUsageEvent(mode="api", audio_seconds=float(secs))])
        usage = normalize_usage_stt(summary.raw_seconds)
        usd = summary.price_usd or Decimal("0")
        crud_cost.add_event(
            db,
            ts_utc=datetime.now(timezone.utc),
            product="stt",
            model=getattr(config, "DEFAULT_STT_MODEL", "CLOVA_STT"),
            llm_tokens=0,
            embedding_tokens=0,
            audio_seconds=int(usage["audio_seconds"]),
            cost_usd=usd,
        )
    except Exception as e:
        log.exception("api-cost stt record failed: %s", e)

    # 3) QA 여부
    qa_mode = any(
        [
            knowledge_id is not None,
            session_id is not None,
            style is not None,
            block_inappropriate is not None,
            restrict_non_tech is not None,
            suggest_agent_handoff is not None,
        ]
    )
    if not qa_mode:
        return STTResponse(text=text)

    if session_id is not None:
        _ensure_session(db, session_id)

    flags = {
        k: v
        for k, v in {
            "block_inappropriate": block_inappropriate,
            "restrict_non_tech": restrict_non_tech,
            "suggest_agent_handoff": suggest_agent_handoff,
        }.items()
        if v is not None
    }

    # 세션이 있으면 ask_in_session과 동일하게 로그 남김
    if session_id is not None:
        crud_chat.create_message(
            db,
            session_id=session_id,
            role="user",
            content=text,
            vector_memory=None,
            response_latency_ms=None,
            extra_data={
                "knowledge_id": knowledge_id,
                "top_k": top_k,
                "style": style,
                "policy_flags": flags,
                "few_shot_profile": few_shot_profile,
                "source": "voice",
                "lang": lang,
            },
        )

    t0 = time.perf_counter()
    resp = _run_qa(
        db,
        question=text,
        knowledge_id=knowledge_id,
        top_k=top_k,
        session_id=session_id,
        policy_flags=flags,
        style=style,
        few_shot_profile=few_shot_profile,
    )
    latency_ms = int((time.perf_counter() - t0) * 1000)

    if resp is None:
        raise HTTPException(status_code=502, detail="_run_qa returned None")

    if session_id is not None:
        crud_chat.create_message(
            db,
            session_id=session_id,
            role="assistant",
            content=resp.answer,
            vector_memory=None,
            response_latency_ms=latency_ms,
            extra_data=jsonable_encoder(
                {
                    "knowledge_id": knowledge_id,
                    "top_k": top_k,
                    "style": style,
                    "policy_flags": flags,
                    "few_shot_profile": few_shot_profile,
                    "sources": _dump_sources(resp),
                    "source": "voice",
                    "lang": lang,
                }
            ),
        )

    return resp


def list_session_messages_service(
    db: Session,
    *,
    session_id: int,
    offset: int,
    limit: int,
    role: Optional[Literal["user", "assistant"]],
) -> List[Dict[str, Any]]:
    _ensure_session(db, session_id)

    rows = crud_chat.list_messages(
        db,
        session_id=session_id,
        offset=offset,
        limit=limit,
        role=role,
    )
    return [
        {
            "message_id": getattr(m, "message_id", None) or getattr(m, "id", None),
            "session_id": m.session_id,
            "role": m.role,
            "content": m.content,
            "created_at": m.created_at,
            "response_latency_ms": getattr(m, "response_latency_ms", None),
            "extra_data": getattr(m, "extra_data", None),
        }
        for m in rows
    ]
