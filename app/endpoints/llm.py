# app/endpoints/llm.py
from __future__ import annotations

import logging
import os
import subprocess
import tempfile
import time
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any, Dict, List, Literal, Optional, Union

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile, status
from fastapi.encoders import jsonable_encoder
from sqlalchemy.orm import Session

from core import config
from core.pricing import ClovaSttUsageEvent, estimate_clova_stt, normalize_usage_stt
from crud import api_cost as crud_cost
from crud import chat as crud_chat
from database.session import get_db
from langchain_service.llm.runner import _run_qa
from schemas.llm import ChatQARequest, QAResponse, STTResponse
from service.stt import _clova_transcribe, _ensure_wav_16k_mono, _wav_duration_seconds

log = logging.getLogger("api_cost")

router = APIRouter(prefix="/llm", tags=["LLM"])


def _probe_duration_seconds(data: bytes) -> float:
    """ffprobe로 비-WAV 파일 길이 추출 (실패 시 0.0)."""
    tmp_name: Optional[str] = None
    try:
        with tempfile.NamedTemporaryFile(delete=False) as tmp:
            tmp_name = tmp.name
            tmp.write(data)
            tmp.flush()

        result = subprocess.run(
            [
                "ffprobe",
                "-v",
                "error",
                "-show_entries",
                "format=duration",
                "-of",
                "default=noprint_wrappers=1:nokey=1",
                tmp_name,
            ],
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
        secs = float((result.stdout or "").strip() or "0")
        return max(0.0, secs)
    except Exception:
        return 0.0
    finally:
        if tmp_name:
            try:
                os.remove(tmp_name)
            except Exception:
                pass


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


@router.post("/chat/sessions/{session_id}/qa", response_model=QAResponse, summary="LLM 입력창")
def ask_in_session(session_id: int, payload: ChatQARequest, db: Session = Depends(get_db)) -> QAResponse:
    _ensure_session(db, session_id)

    if getattr(payload, "role", "user") != "user":
        raise HTTPException(status_code=400, detail="role must be 'user'")

    few_shot_profile: str = str(getattr(payload, "few_shot_profile", None) or "support_md")
    flags = _extract_policy_flags(payload)

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

    sources_dump = []
    for s in (getattr(resp, "sources", None) or []):
        if hasattr(s, "model_dump"):
            sources_dump.append(s.model_dump())
        else:
            sources_dump.append(jsonable_encoder(s))

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
                "sources": sources_dump,
                "source": "text",
            }
        ),
    )

    return resp


@router.post("/clova_stt", response_model=Union[STTResponse, QAResponse])
async def clova_stt(
    file: UploadFile = File(...),
    lang: str = Form("ko-KR"),
    db: Session = Depends(get_db),
    # QA 모드용 선택 파라미터
    knowledge_id: Optional[int] = Form(None),
    top_k: int = Form(5),
    session_id: Optional[int] = Form(None),
    style: Optional[str] = Form(None),
    block_inappropriate: Optional[bool] = Form(None),
    restrict_non_tech: Optional[bool] = Form(None),
    suggest_agent_handoff: Optional[bool] = Form(None),
    few_shot_profile: str = Form("support_md"),
):
    try:
        raw = await file.read()
        wav = _ensure_wav_16k_mono(raw, file.content_type or "")

        # 1) STT
        text = _clova_transcribe(wav, lang).strip()
        if not text:
            raise ValueError("empty transcription")

        # 2) 길이 산출 → 비용 기록
        secs = _wav_duration_seconds(wav)
        if secs <= 0:
            secs = _probe_duration_seconds(raw)
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

        # 3) QA 여부 결정
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
            sources_dump = []
            for s in (getattr(resp, "sources", None) or []):
                if hasattr(s, "model_dump"):
                    sources_dump.append(s.model_dump())
                else:
                    sources_dump.append(jsonable_encoder(s))

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
                        "sources": sources_dump,
                        "source": "voice",
                        "lang": lang,
                    }
                ),
            )

        return resp

    except ValueError:
        raise HTTPException(status_code=422, detail="empty transcription")
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"clova_stt failed: {e}")


@router.get(
    "/chat/sessions/{session_id}/messages",
    summary="세션 메시지 조회(user+assistant)",
    response_model=List[Dict[str, Any]],
)
def get_session_messages(
    session_id: int,
    offset: int = 0,
    limit: int = 200,
    role: Optional[Literal["user", "assistant"]] = None,
    db: Session = Depends(get_db),
):
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
