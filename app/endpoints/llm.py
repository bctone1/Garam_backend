# APP/llm.py
from __future__ import annotations

from typing import Iterable, Optional
import os, tempfile, subprocess, shutil, requests, io, wave, logging
from datetime import datetime, timezone
from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException, status, UploadFile, File, Form
from sqlalchemy.orm import Session

from crud import chat as crud_chat
from crud import knowledge as crud_knowledge
from database.session import get_db, SessionLocal
from langchain_service.chain.qa_chain import make_qa_chain
from langchain_service.embedding.get_vector import text_to_vector, _to_vector

from langchain_service.llm.runner import _update_last_user_vector, _build_sources, _run_qa
from langchain_service.llm.setup import get_llm
from schemas.llm import ChatQARequest, QARequest, QAResponse, QASource
from service.stt import transcribe_bytes
from schemas.llm import STTResponse, STTQAParams
from fastapi.responses import StreamingResponse
from core import config
from core.pricing import (
    tokens_for_texts,              # tiktoken 토큰 계산
    estimate_llm_cost_usd,         # LLM 비용
    ClovaSttUsageEvent,            # STT 사용량 구조체
    estimate_clova_stt,            # STT 비용 추정
    normalize_usage_stt,           # STT 사용량 정규화
)
from crud import api_cost as crud_cost
from service.stt import _wav_duration_seconds,_ensure_wav_16k_mono,_clova_transcribe

log = logging.getLogger("api_cost")

router = APIRouter(prefix="/llm", tags=["LLM"])
CLOVA_STT_URL = os.getenv("CLOVA_STT_URL")


def _ensure_session(db: Session, session_id: int) -> None:
    if not crud_chat.get_session(db, session_id):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="session not found")


@router.post("/qa/stream")
def ask_stream(payload: QARequest, db: Session = Depends(get_db)):
    try:
        chain = make_qa_chain(
            db, get_llm, text_to_vector,
            knowledge_id=payload.knowledge_id, top_k=payload.top_k,
            policy_flags={}, style=payload.style or "friendly",
            streaming=True,
        )
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc))

    model = getattr(config, "DEFAULT_CHAT_MODEL", "gpt-4o-mini")

    def stream_gen():
        full = ""
        try:
            for chunk in chain.stream({"question": payload.question}):
                full += chunk
                yield chunk
        finally:
            # 스트림 종료 시 토큰·비용 기록
            try:
                total = tokens_for_texts(model, [payload.question, full])
                usd = estimate_llm_cost_usd(model=model, total_tokens=total)
                with SessionLocal() as s:
                    crud_cost.add_event(
                        s,
                        ts_utc=datetime.now(timezone.utc),
                        product="llm", model=model,
                        llm_tokens=total, embedding_tokens=0,
                        audio_seconds=0, cost_usd=usd,
                    )
            except Exception as e:
                log.exception("api-cost llm record failed: %s", e)

    return StreamingResponse(stream_gen(), media_type="text/plain")
    # def stream_gen():
    #     """LLM으로부터 토큰 스트림을 순차적으로 전송"""
    #     try:
    #         for chunk in chain.stream({"question": payload.question}):
    #             yield chunk  # 각 토큰을 그대로 클라이언트에 전송
    #     except Exception as e:
    #         yield f"\n[error] {e}"

    # text/event-stream 으로도 가능. (브라우저 실시간 보기용)
    # return StreamingResponse(stream_gen(), media_type="text/plain")

@router.post("/chat/sessions/{session_id}/qa", response_model=QAResponse)
def ask_in_session(session_id: int, payload: ChatQARequest, db: Session = Depends(get_db)) -> QAResponse:
    _ensure_session(db, session_id)
    flags = {
        k: v
        for k, v in {
            "block_inappropriate": payload.block_inappropriate,
            "restrict_non_tech": payload.restrict_non_tech,
            "suggest_agent_handoff": payload.suggest_agent_handoff,
        }.items()
        if v is not None
    }
    return _run_qa(
        db,
        question=payload.question,
        knowledge_id=payload.knowledge_id,
        top_k=payload.top_k,
        session_id=session_id,
        policy_flags=flags,
        style=payload.style,
    )


@router.post("/qa", response_model=QAResponse)
def ask_global(payload: QARequest, db: Session = Depends(get_db)) -> QAResponse:
    flags = {
        k: v
        for k, v in {
            "block_inappropriate": payload.block_inappropriate,
            "restrict_non_tech": payload.restrict_non_tech,
            "suggest_agent_handoff": payload.suggest_agent_handoff,
        }.items()
        if v is not None
    }
    session_id = payload.session_id
    if session_id is not None:
        _ensure_session(db, session_id)
    return _run_qa(
        db,
        question=payload.question,
        knowledge_id=payload.knowledge_id,
        top_k=payload.top_k,
        session_id=session_id,
        policy_flags=flags,
        style=payload.style,
    )


@router.post("/qa/query", response_model=QAResponse)
def ask_global_alias(payload: QARequest, db: Session = Depends(get_db)) -> QAResponse:
    return ask_global(payload, db)


# ===== STT =====
@router.post("/stt", response_model=STTResponse)
async def stt(file: UploadFile = File(...), lang: str = Form("ko-KR")):
    try:
        text = transcribe_bytes(await file.read(), file.content_type or "", lang)
        return STTResponse(text=text)
    except ValueError:
        raise HTTPException(status_code=422, detail="empty transcription")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"stt failed: {e}")


@router.post("/stt_qa", response_model=QAResponse)
async def stt_qa(
    file: UploadFile = File(...),
    params: STTQAParams = Depends(STTQAParams.as_form),
    db: Session = Depends(get_db),
):
    try:
        text = transcribe_bytes(await file.read(), file.content_type or "", params.lang)
        flags = {}
        for k in ("block_inappropriate", "restrict_non_tech", "suggest_agent_handoff"):
            v = getattr(params, k, None)
            if v is not None:
                flags[k] = v
        return _run_qa(
            db,
            question=text,
            knowledge_id=params.knowledge_id,
            top_k=params.top_k,
            session_id=params.session_id,
            policy_flags=flags,
            style=params.style,
        )
    except ValueError:
        raise HTTPException(status_code=422, detail="empty transcription")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"stt failed: {e}")


# ===== Clova STT =====
@router.post("/clova_stt", response_model=STTResponse)
async def clova_stt(file: UploadFile = File(...), lang: str = Form("ko-KR"), db: Session = Depends(get_db)):
    try:
        b = await file.read()
        wav = _ensure_wav_16k_mono(b, file.content_type or "")
        text = _clova_transcribe(wav, lang)
        try:
            secs = _wav_duration_seconds(wav)
            summary = estimate_clova_stt([ClovaSttUsageEvent(mode="api", audio_seconds=secs)])
            usage = normalize_usage_stt(summary.raw_seconds)
            usd = summary.price_usd or Decimal("0")
            log.info("api-cost: will record stt secs=%s bill=%s usd=%s", summary.raw_seconds, usage["audio_seconds"], usd)
            crud_cost.add_event(
                db,
                ts_utc=datetime.now(timezone.utc),
                product="stt",
                model=getattr(config, "DEFAULT_STT_MODEL", "CLOVA_STT"),
                llm_tokens=0,
                embedding_tokens=0,
                audio_seconds=usage["audio_seconds"],
                cost_usd=usd,
            )
            log.info("api-cost: recorded stt secs=%s bill=%s usd=%s", summary.raw_seconds, usage["audio_seconds"], usd)
        except Exception as e:
            log.exception("api-cost stt record failed: %s", e)
        return STTResponse(text=text)
    except ValueError:
        raise HTTPException(status_code=422, detail="empty transcription")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"stt failed: {e}")


@router.post("/clova_stt_qa", response_model=QAResponse)
async def clova_stt_qa(
    file: UploadFile = File(...),
    params: STTQAParams = Depends(STTQAParams.as_form),
    db: Session = Depends(get_db),
):
    try:
        b = await file.read()
        wav = _ensure_wav_16k_mono(b, file.content_type or "")
        text = _clova_transcribe(wav, params.lang)
        try:
            secs = _wav_duration_seconds(wav)
            summary = estimate_clova_stt([ClovaSttUsageEvent(mode="api", audio_seconds=secs)])
            usage = normalize_usage_stt(summary.raw_seconds)
            usd = summary.price_usd or Decimal("0")
            log.info("api-cost: will record stt secs=%s bill=%s usd=%s", summary.raw_seconds, usage["audio_seconds"], usd)
            crud_cost.add_event(
                db,
                ts_utc=datetime.now(timezone.utc),
                product="stt",
                model=getattr(config, "DEFAULT_STT_MODEL", "CLOVA_STT"),
                llm_tokens=0,
                embedding_tokens=0,
                audio_seconds=usage["audio_seconds"],
                cost_usd=usd,
            )
            log.info("api-cost: recorded stt secs=%s bill=%s usd=%s", summary.raw_seconds, usage["audio_seconds"], usd)
        except Exception as e:
            log.exception("api-cost stt record failed: %s", e)

        flags = {}
        for k in ("block_inappropriate", "restrict_non_tech", "suggest_agent_handoff"):
            v = getattr(params, k, None)
            if v is not None:
                flags[k] = v
        return _run_qa(
            db,
            question=text,
            knowledge_id=params.knowledge_id,
            top_k=params.top_k,
            session_id=params.session_id,
            policy_flags=flags,
            style=params.style,
        )
    except ValueError:
        raise HTTPException(status_code=422, detail="empty transcription")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"stt failed: {e}")
