# app/endpoints/llm.py
from __future__ import annotations

from typing import Optional, Union, Any, Dict, List, Literal
import os
import tempfile
import subprocess
import logging
import time
from datetime import datetime, timezone
from decimal import Decimal
import json

from fastapi import APIRouter, Depends, HTTPException, status, UploadFile, File, Form
from fastapi.responses import StreamingResponse
from fastapi.encoders import jsonable_encoder
from sqlalchemy.orm import Session

from database.session import get_db
from crud import chat as crud_chat
from crud import api_cost as crud_cost

from core import config
from core.pricing import (
    tokens_for_texts,
    estimate_llm_cost_usd,
    ClovaSttUsageEvent,
    estimate_clova_stt,
    normalize_usage_stt,
)

from schemas.llm import ChatQARequest, QARequest, QAResponse, STTResponse, STTQAParams

from langchain_service.chain.qa_chain import make_qa_chain
from langchain_service.embedding.get_vector import text_to_vector, _to_vector
from langchain_service.llm.setup import get_llm
from langchain_service.llm.runner import _run_qa
from langchain_service.prompt.style import build_system_prompt
from langchain_service.prompt.few_shots import load_few_shot_profile

from service.knowledge_retrieval import retrieve_topk_hybrid
from service.stt import transcribe_bytes
from service.stt import _wav_duration_seconds, _ensure_wav_16k_mono, _clova_transcribe

try:
    from langchain_community.callbacks import get_openai_callback
except Exception:
    get_openai_callback = None

log = logging.getLogger("api_cost")

router = APIRouter(prefix="/llm", tags=["LLM"])
CLOVA_STT_URL = os.getenv("CLOVA_STT_URL")

MAX_CTX_CHARS = 12000


def _probe_duration_seconds(data: bytes) -> float:
    """ffprobe로 비-WAV 파일 길이 추출"""
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


def _load_profile_for_estimate(name: str) -> Optional[dict]:
    for cand in [name, "support_v1", "support_v1"]:
        try:
            return load_few_shot_profile(cand)
        except FileNotFoundError:
            continue
        except Exception:
            continue
    return None


def _prompt_parts_for_estimate(
    *,
    question: str,
    context_text: str,
    style: Optional[str],
    policy_flags: Optional[dict],
    force_json_output: bool,
    few_shot_profile: str,
) -> list[str]:
    """
    스트리밍 비용 추정용: system + (json 계약/룰/예시) + 컨텍스트 + 질문
    """
    system_txt = build_system_prompt(style=(style or "friendly"), **(policy_flags or {}))

    parts: list[str] = [system_txt]

    if force_json_output:
        prof = _load_profile_for_estimate(few_shot_profile)
        if prof:
            contract = prof.get("output_contract") or {}
            rules = prof.get("rules") or []
            parts.append(
                "너는 반드시 아래 출력 계약을 지켜서 'JSON 객체'만 출력해야 해."
                "(코드블록/마크다운/설명 문장 금지)"
            )
            parts.append(json.dumps(contract, ensure_ascii=False))
            if rules:
                parts.append("규칙:\n- " + "\n- ".join(rules))

            # few-shot도 토큰에 포함(대략 추정)
            for ex in prof.get("examples", []) or []:
                u = ex.get("user", "")
                a = ex.get("assistant", {})
                parts.append(f"[few-shot user]\n{u}")
                parts.append(f"[few-shot assistant]\n{json.dumps(a, ensure_ascii=False)}")

    parts.extend(
        [
            "다음 컨텍스트를 참고해.",
            "[컨텍스트 시작]",
            context_text,
            "[컨텍스트 끝]",
            "질문: " + question,
            "force_clarify: False",
        ]
    )
    return parts


def _retrieve_sources_and_context(
    db: Session,
    *,
    vector: list[float],
    knowledge_id: Optional[int],
    top_k: int,
    question: str,
) -> tuple[list[str], str]:
    """
    스트리밍 엔드포인트용(간단): sources(text 리스트) + context_text
    """
    chunks = retrieve_topk_hybrid(
        db,
        query_vector=vector,
        knowledge_id=knowledge_id,
        top_k=top_k,
        query_text=question,
    )
    texts = [getattr(c, "chunk_text", "") or "" for c in chunks]
    context_text = ("\n\n".join(texts))[:MAX_CTX_CHARS]
    return texts, context_text


@router.post("/qa/stream")
def ask_stream(payload: QARequest, db: Session = Depends(get_db)):
    # JSON 모드 기본 ON (payload에 있으면 그 값을 우선)
    force_json_output: bool = bool(getattr(payload, "force_json_output", False))
    few_shot_profile: str = str(getattr(payload, "few_shot_profile", "support_v1") or "support_v1")

    # 체인 생성 전 컨텍스트 확보(보정 토큰 계산용)
    try:
        vec = _to_vector(payload.question)
    except Exception as exc:
        raise HTTPException(status_code=503, detail="임베딩 생성에 실패했습니다.") from exc

    _, context_text = _retrieve_sources_and_context(
        db,
        vector=vec,
        knowledge_id=payload.knowledge_id,
        top_k=payload.top_k,
        question=payload.question,
    )

    provider = getattr(config, "LLM_PROVIDER", "openai").lower()
    model = getattr(config, "LLM_MODEL", getattr(config, "DEFAULT_CHAT_MODEL", "gpt-4o-mini"))
    style = payload.style or "friendly"
    flags: dict = {}

    def stream_gen():
        if provider == "openai" and get_openai_callback is not None:
            with get_openai_callback() as cb:
                try:
                    chain = make_qa_chain(
                        db,
                        get_llm,
                        text_to_vector,
                        knowledge_id=payload.knowledge_id,
                        top_k=payload.top_k,
                        policy_flags=flags,
                        style=style,
                        streaming=True,
                        callbacks=[cb],
                        use_input_context=True,
                        force_json_output=force_json_output,
                        few_shot_profile=few_shot_profile,
                    )
                except RuntimeError as exc:
                    raise HTTPException(status_code=503, detail=str(exc))

                full = ""
                try:
                    for chunk in chain.stream(
                        {"question": payload.question, "context": context_text},
                        config={"callbacks": [cb]},
                    ):
                        full += chunk
                        yield chunk
                finally:
                    try:
                        prompt_parts = _prompt_parts_for_estimate(
                            question=payload.question,
                            context_text=context_text,
                            style=style,
                            policy_flags=flags,
                            force_json_output=force_json_output,
                            few_shot_profile=few_shot_profile,
                        )
                        est_tokens = tokens_for_texts(model, prompt_parts + [full])
                        cb_total = int(getattr(cb, "total_tokens", 0) or 0)
                        total = max(cb_total, est_tokens)

                        usd_cb = Decimal(str(getattr(cb, "total_cost", 0.0) or 0.0))
                        usd_est = estimate_llm_cost_usd(model=model, total_tokens=total)
                        usd = max(usd_cb, usd_est)

                        crud_cost.add_event(
                            db,
                            ts_utc=datetime.now(timezone.utc),
                            product="llm",
                            model=model,
                            llm_tokens=total,
                            embedding_tokens=0,
                            audio_seconds=0,
                            cost_usd=usd,
                        )
                    except Exception as e:
                        log.exception("api-cost llm record failed: %s", e)
        else:
            try:
                chain = make_qa_chain(
                    db,
                    get_llm,
                    text_to_vector,
                    knowledge_id=payload.knowledge_id,
                    top_k=payload.top_k,
                    policy_flags=flags,
                    style=style,
                    streaming=True,
                    use_input_context=True,
                    force_json_output=force_json_output,
                    few_shot_profile=few_shot_profile,
                )
            except RuntimeError as exc:
                raise HTTPException(status_code=503, detail=str(exc))

            full = ""
            try:
                for chunk in chain.stream({"question": payload.question, "context": context_text}):
                    full += chunk
                    yield chunk
            finally:
                try:
                    prompt_parts = _prompt_parts_for_estimate(
                        question=payload.question,
                        context_text=context_text,
                        style=style,
                        policy_flags=flags,
                        force_json_output=force_json_output,
                        few_shot_profile=few_shot_profile,
                    )
                    total = tokens_for_texts(model, prompt_parts + [full])
                    usd = estimate_llm_cost_usd(model=model, total_tokens=total)
                    crud_cost.add_event(
                        db,
                        ts_utc=datetime.now(timezone.utc),
                        product="llm",
                        model=model,
                        llm_tokens=total,
                        embedding_tokens=0,
                        audio_seconds=0,
                        cost_usd=usd,
                    )
                except Exception as e:
                    log.exception("api-cost llm record failed: %s", e)

    # 주의: JSON 모드라도 스트리밍은 중간 조각이 불완전 JSON일 수 있음(클라에서 누적 후 파싱)
    return StreamingResponse(stream_gen(), media_type="text/plain")


@router.post("/chat/sessions/{session_id}/qa", response_model=QAResponse, summary="LLM 입력창")
def ask_in_session(session_id: int, payload: ChatQARequest, db: Session = Depends(get_db)) -> QAResponse:
    _ensure_session(db, session_id)

    if getattr(payload, "role", "user") != "user":
        raise HTTPException(status_code=400, detail="role must be 'user'")

    flags = {
        k: v
        for k, v in {
            "block_inappropriate": getattr(payload, "block_inappropriate", None),
            "restrict_non_tech": getattr(payload, "restrict_non_tech", None),
            "suggest_agent_handoff": getattr(payload, "suggest_agent_handoff", None),
        }.items()
        if v is not None
    }

    force_json_output: bool = bool(getattr(payload, "force_json_output", False))
    few_shot_profile: str = str(getattr(payload, "few_shot_profile", "support_v1") or "support_v1")

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
            "force_json_output": force_json_output,
            "few_shot_profile": few_shot_profile,
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
        force_json_output=force_json_output,
        few_shot_profile=few_shot_profile,
    )
    latency_ms = int((time.perf_counter() - t0) * 1000)

    crud_chat.create_message(
        db,
        session_id=session_id,
        role="assistant",
        content=resp.answer,  # JSON string
        vector_memory=None,
        response_latency_ms=latency_ms,
        extra_data=jsonable_encoder(
            {
                "knowledge_id": payload.knowledge_id,
                "top_k": payload.top_k,
                "style": payload.style,
                "policy_flags": flags,
                "force_json_output": force_json_output,
                "few_shot_profile": few_shot_profile,
                "sources": [s.model_dump() for s in (resp.sources or [])],
            }
        ),
    )

    return resp


@router.post("/qa", response_model=QAResponse)
def ask_global(payload: QARequest, db: Session = Depends(get_db)) -> QAResponse:
    flags = {
        k: v
        for k, v in {
            "block_inappropriate": getattr(payload, "block_inappropriate", None),
            "restrict_non_tech": getattr(payload, "restrict_non_tech", None),
            "suggest_agent_handoff": getattr(payload, "suggest_agent_handoff", None),
        }.items()
        if v is not None
    }

    force_json_output: bool = bool(getattr(payload, "force_json_output", False))
    few_shot_profile: str = str(getattr(payload, "few_shot_profile", "support_v1") or "support_v1")

    session_id = getattr(payload, "session_id", None)
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
        force_json_output=force_json_output,
        few_shot_profile=few_shot_profile,
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
        text = transcribe_bytes(await file.read(), file.content_type or "", params.lang).strip()
        if not text:
            raise ValueError("empty transcription")

        flags = {}
        for k in ("block_inappropriate", "restrict_non_tech", "suggest_agent_handoff"):
            v = getattr(params, k, None)
            if v is not None:
                flags[k] = v

        force_json_output: bool = bool(getattr(params, "force_json_output", False))
        few_shot_profile: str = str(getattr(params, "few_shot_profile", "support_v1") or "support_v1")

        return _run_qa(
            db,
            question=text,
            knowledge_id=params.knowledge_id,
            top_k=params.top_k,
            session_id=params.session_id,
            policy_flags=flags,
            style=params.style,
            force_json_output=force_json_output,
            few_shot_profile=few_shot_profile,
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
    # JSON 모드 (form으로도 받게)
    force_json_output: bool = Form(False),
    few_shot_profile: str = Form("support_v1"),
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

        flags = {
            k: v
            for k, v in {
                "block_inappropriate": block_inappropriate,
                "restrict_non_tech": restrict_non_tech,
                "suggest_agent_handoff": suggest_agent_handoff,
            }.items()
            if v is not None
        }

        return _run_qa(
            db,
            question=text,
            knowledge_id=knowledge_id,
            top_k=top_k,
            session_id=session_id,
            policy_flags=flags,
            style=style,
            force_json_output=bool(force_json_output),
            few_shot_profile=str(few_shot_profile or "support_v1"),
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
