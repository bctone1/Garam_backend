# APP/llm.py
from __future__ import annotations

from typing import Iterable, Optional, Union, Any, Dict, List, Literal

import os, tempfile, subprocess, shutil, requests, io, wave, logging, time
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
from fastapi.encoders import jsonable_encoder
from langchain_service.prompt.style import build_system_prompt
try:
    from langchain_community.callbacks import get_openai_callback
except Exception:
    get_openai_callback = None

log = logging.getLogger("api_cost")

router = APIRouter(prefix="/llm", tags=["LLM"])
CLOVA_STT_URL = os.getenv("CLOVA_STT_URL")

# 프롬프트 전체 조각 생성
def _prompt_parts_for_estimate(question: str, context_text: str, style: Optional[str], policy_flags: Optional[dict]) -> list[str]:
    system_txt = build_system_prompt(style=(style or "friendly"), **(policy_flags or {}))
    rule_txt = (
        "규칙: 제공된 컨텍스트를 우선하여 답하고, 정말 관련이 없을 때만 "
        "짧게 '해당내용은 찾을 수 없음'이라고 답하라."
    )
    return [
        system_txt,
        rule_txt,
        "다음 컨텍스트만 근거로 답하세요.\n[컨텍스트 시작]",
        context_text,
        "[컨텍스트 끝]",
        "질문: " + question,
    ]



def _probe_duration_seconds(data: bytes) -> float:
    """ffprobe로 비-WAV 파일 길이 추출"""
    try:
        with tempfile.NamedTemporaryFile(delete=False) as tmp:
            tmp.write(data)
            tmp.flush()
            result = subprocess.run(
                ["ffprobe", "-v", "error", "-show_entries", "format=duration",
                 "-of", "default=noprint_wrappers=1:nokey=1", tmp.name],
                capture_output=True, text=True, timeout=5
            )
            secs = float(result.stdout.strip())
            return max(0.0, secs)
    except Exception:
        return 0.0
    finally:
        try: os.remove(tmp.name)
        except: pass



def _ensure_session(db: Session, session_id: int) -> None:
    if not crud_chat.get_session(db, session_id):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="session not found")


# 스트리밍 엔드포인트 집계 버전
@router.post("/qa/stream")
def ask_stream(payload: QARequest, db: Session = Depends(get_db)):
    # 체인 생성 전 컨텍스트 확보(보정 토큰 계산용)
    try:
        vec = _to_vector(payload.question)
    except Exception as exc:
        raise HTTPException(status_code=503, detail="임베딩 생성에 실패했습니다.") from exc

    sources = _build_sources(db, vec, payload.knowledge_id, payload.top_k)
    context_text = ("\n\n".join(s.text for s in sources))[:12000]

    provider = getattr(config, "LLM_PROVIDER", "openai").lower()
    model = getattr(config, "LLM_MODEL", getattr(config, "DEFAULT_CHAT_MODEL", "gpt-4o-mini"))
    style = payload.style or "friendly"
    flags: dict = {}  # 필요 시 확장

    def stream_gen():
        # OpenAI 콜백 가능한 경우: 콜백 + 보정치 동시 사용
        if provider == "openai" and get_openai_callback is not None:
            with get_openai_callback() as cb:
                try:
                    chain = make_qa_chain(
                        db, get_llm, text_to_vector,
                        knowledge_id=payload.knowledge_id, top_k=payload.top_k,
                        policy_flags=flags, style=style, streaming=True, callbacks=[cb],
                    )
                except RuntimeError as exc:
                    raise HTTPException(status_code=503, detail=str(exc))

                full = ""
                try:
                    for chunk in chain.stream({"question": payload.question}, config={"callbacks": [cb]}):
                        full += chunk
                        yield chunk
                finally:
                    try:
                        prompt_parts = _prompt_parts_for_estimate(payload.question, context_text, style, flags)
                        est_tokens = tokens_for_texts(model, prompt_parts + [full])
                        cb_total = int(getattr(cb, "total_tokens", 0) or 0)
                        total = max(cb_total, est_tokens)

                        usd_cb = Decimal(str(getattr(cb, "total_cost", 0.0) or 0.0))
                        usd_est = estimate_llm_cost_usd(model=model, total_tokens=total)
                        usd = max(usd_cb, usd_est)

                        crud_cost.add_event(
                            db,
                            ts_utc=datetime.now(timezone.utc),
                            product="llm", model=model,
                            llm_tokens=total, embedding_tokens=0,
                            audio_seconds=0, cost_usd=usd,
                        )
                    except Exception as e:
                        log.exception("api-cost llm record failed: %s", e)
        else:
            # 콜백 불가(타사 모델 등): 프롬프트 전체 기준 추정
            try:
                chain = make_qa_chain(
                    db, get_llm, text_to_vector,
                    knowledge_id=payload.knowledge_id, top_k=payload.top_k,
                    policy_flags=flags, style=style, streaming=True,
                )
            except RuntimeError as exc:
                raise HTTPException(status_code=503, detail=str(exc))

            full = ""
            try:
                for chunk in chain.stream({"question": payload.question}):
                    full += chunk
                    yield chunk
            finally:
                try:
                    prompt_parts = _prompt_parts_for_estimate(payload.question, context_text, style, flags)
                    total = tokens_for_texts(model, prompt_parts + [full])
                    usd = estimate_llm_cost_usd(model=model, total_tokens=total)
                    crud_cost.add_event(
                        db,
                        ts_utc=datetime.now(timezone.utc),
                        product="llm", model=model,
                        llm_tokens=total, embedding_tokens=0,
                        audio_seconds=0, cost_usd=usd,
                    )
                except Exception as e:
                    log.exception("api-cost llm record failed: %s", e)

    return StreamingResponse(stream_gen(), media_type="text/plain")



@router.post("/chat/sessions/{session_id}/qa", response_model=QAResponse, summary="LLM 입력창")
def ask_in_session(session_id: int, payload: ChatQARequest, db: Session = Depends(get_db)) -> QAResponse:
    _ensure_session(db, session_id)

    # 이 엔드포인트는 유저 질문을 받는 용도
    if getattr(payload, "role", "user") != "user":
        raise HTTPException(status_code=400, detail="role must be 'user'")

    flags = {
        k: v
        for k, v in {
            "block_inappropriate": payload.block_inappropriate,
            "restrict_non_tech": payload.restrict_non_tech,
            "suggest_agent_handoff": payload.suggest_agent_handoff,
        }.items()
        if v is not None
    }

    # 1) user 메시지 저장 (vector_memory는 우선 None으로도 OK)
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
    )
    latency_ms = int((time.perf_counter() - t0) * 1000)

    # 2) assistant 메시지 저장
    crud_chat.create_message(
        db,
        session_id=session_id,
        role="assistant",
        content=resp.answer,
        vector_memory=None,
        response_latency_ms=latency_ms,
        extra_data=jsonable_encoder({
            "knowledge_id": payload.knowledge_id,
            "top_k": payload.top_k,
            "style": payload.style,
            "policy_flags": flags,
            "sources": [s.model_dump() for s in (resp.sources or [])],
        }),
    )

    return resp


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
            log.info(
                "api-cost: will record stt secs=%s bill=%s usd=%s",
                summary.raw_seconds, usage["audio_seconds"], usd
            )
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
            log.info(
                "api-cost: recorded stt secs=%s bill=%s usd=%s",
                summary.raw_seconds, usage["audio_seconds"], usd
            )
        except Exception as e:
            log.exception("api-cost stt record failed: %s", e)

        # 3) QA 여부 결정
        qa_mode = any([
            knowledge_id is not None,
            session_id is not None,
            style is not None,
            block_inappropriate is not None,
            restrict_non_tech is not None,
            suggest_agent_handoff is not None,
        ])
        if not qa_mode:
            return STTResponse(text=text)

        flags = {
            k: v for k, v in {
                "block_inappropriate": block_inappropriate,
                "restrict_non_tech": restrict_non_tech,
                "suggest_agent_handoff": suggest_agent_handoff,
            }.items() if v is not None
        }

        return _run_qa(
            db,
            question=text,
            knowledge_id=knowledge_id,
            top_k=top_k,
            session_id=session_id,
            policy_flags=flags,
            style=style,
        )

    except ValueError:
        raise HTTPException(status_code=422, detail="empty transcription")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"stt failed: {e}")

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

    # ORM → JSON-safe dict
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
