# service/llm_service.py
from __future__ import annotations

import logging
import re
import time
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any, Dict, List, Literal, Optional, Union

from fastapi import HTTPException, status
from fastapi.encoders import jsonable_encoder
from sqlalchemy import text as sa_text
from sqlalchemy.orm import Session

from core import config
from core.pricing import ClovaSttUsageEvent, estimate_clova_stt, normalize_usage_stt
from crud import api_cost as crud_cost
from crud import chat as crud_chat
from crud import chat_history as crud_chat_history
from langchain_service.llm.runner import _run_qa
from schemas.llm import ChatQARequest, QAResponse, STTResponse
from service.stt import (
    clova_transcribe,
    ensure_wav_16k_mono,
    probe_duration_seconds,
    wav_duration_seconds,
)

log = logging.getLogger("api_cost")

# =========================================================
# category classification (rule -> (optional) embedding -> (optional) llm)
# =========================================================
_USE_QC_EMBEDDING: bool = bool(getattr(config, "CHAT_CATEGORY_USE_EMBEDDING", False))
_DEFAULT_CHANNEL = "web"


# 아주 가벼운 룰(초기버전). quick_category.name이 한글/영문 어떤 형태든 매칭되게 "후보 토큰"을 넓게 둠.
_RULES: list[tuple[list[str], list[str]]] = [
    # triggers, target name candidates (quick_category.name 안에서 찾을 토큰들)
    (["키오스크", "kiosk", "테이블오더", "tableorder", "table order", "주문", "테이블"], ["kiosk", "키오스크", "테이블오더"]),
    (["포스", "pos", "프린터", "printer", "용지", "출력", "인쇄", "프린트"], ["pos", "포스", "프린터", "출력", "인쇄"]),
    (["단말기", "terminal", "결제", "승인", "취소", "카드", "van", "ic", "msr"], ["terminal", "단말기", "결제"]),
    (["설치", "install", "다운로드", "driver", "드라이버", "업데이트", "update"], ["install", "설치", "드라이버", "업데이트"]),
]


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


def _record_failure_suggestion(
    db: Session,
    *,
    session_id: int,
    question_text: str,
    assistant_message: Any,
    resp: QAResponse,
) -> None:
    if getattr(resp, "status", None) == "ok":
        return

    message_id = getattr(assistant_message, "id", None) or getattr(
        assistant_message, "message_id", None
    )
    if not message_id:
        log.warning("knowledge_suggestion skipped: missing message_id")
        return

    try:
        crud_chat_history.upsert_pending_knowledge_suggestion(
            db,
            session_id=session_id,
            message_id=int(message_id),
            question_text=question_text,
            assistant_answer=resp.answer,
            reason_code=resp.reason_code,
            retrieval_meta=getattr(resp, "retrieval_meta", None),
            answer_status="error",
        )
    except Exception:
        log.exception("knowledge_suggestion upsert failed")


def _extract_keywords_simple(text: str, *, max_items: int = 12) -> list[str]:
    """
    초기 버전: 형태소 분석기 없을 때도 동작하는 가벼운 키워드 추출.
    - 한글/영문/숫자 토큰을 뽑고 중복 제거
    - 너무 짧은 토큰 제거
    """
    s = (text or "").strip().lower()
    if not s:
        return []
    tokens = re.findall(r"[0-9a-zA-Z가-힣]{2,}", s)
    seen: set[str] = set()
    out: list[str] = []
    for t in tokens:
        if t in seen:
            continue
        seen.add(t)
        out.append(t)
        if len(out) >= max_items:
            break
    return out


def _fetch_quick_categories(db: Session) -> list[dict]:
    """
    모델 import 의존성을 피하려고 SQL로만 읽음.
    quick_category: (id, name, description)
    """
    rows = db.execute(
        sa_text(
            """
            SELECT
              id,
              name,
              COALESCE(description, '') AS description
            FROM quick_category
            ORDER BY sort_order ASC, id ASC
            """
        )
    ).mappings().all()
    return list(rows)


def _get_etc_quick_category(qcs: list[dict]) -> tuple[Optional[int], Optional[str]]:
    for qc in qcs:
        raw_name = str(qc.get("name", "")).strip()
        name = raw_name.lower()
        if name in {"etc", "기타"}:
            return int(qc["id"]), raw_name
    return None, None


def _normalize_channel(channel: Optional[str]) -> str:
    if channel is not None:
        normalized = str(channel).strip().lower()
        if normalized:
            return normalized
    return _DEFAULT_CHANNEL




def _pick_qc_by_name_token(qcs: list[dict], name_tokens: list[str]) -> Optional[tuple[int, str]]:
    """
    quick_category.name/description에서 토큰이 가장 잘 맞는 항목을 선택.
    """
    best: Optional[tuple[int, str, int]] = None  # (id, name, score)
    for qc in qcs:
        name = str(qc.get("name", "") or "")
        desc = str(qc.get("description", "") or "")
        hay = (name + " " + desc).lower().replace(" ", "")
        score = 0
        for tok in name_tokens:
            t = tok.lower().replace(" ", "")
            if t and t in hay:
                score += 1
        if score <= 0:
            continue
        if best is None or score > best[2]:
            best = (int(qc["id"]), name, score)
    if best:
        return best[0], best[1]
    return None


def _classify_quick_category(
    db: Session,
    *,
    text: str,
    keywords: list[str],
) -> tuple[Optional[int], Optional[str]]:
    """
    반환: (quick_category_id, category_name_cache)
    - 룰 기반 -> (선택) 임베딩 -> (미구현) LLM
    - 최종적으로 etc_id가 있으면 etc로 반환
    """
    qcs = _fetch_quick_categories(db)
    if not qcs:
        return None, None

    etc_id, etc_name = _get_etc_quick_category(qcs)

    # 1) 룰 기반
    hay = (text or "").lower()
    for triggers, target_tokens in _RULES:
        if any(t.lower() in hay for t in triggers):
            picked = _pick_qc_by_name_token(qcs, target_tokens)
            if picked:
                return picked[0], picked[1]

    # 2) (선택) 임베딩 기반 - 현재는 플래그로만 on
    #    quick_category 임베딩을 DB에 저장하는 구조가 생기면 여기 대신 DB vector로 바꾸는 걸 추천.
    if _USE_QC_EMBEDDING:
        try:
            from langchain_service.embedding.get_vector import text_to_vector  # type: ignore
        except Exception:
            text_to_vector = None  # type: ignore

        if text_to_vector is not None:
            try:
                q_vec = text_to_vector(text)
                if q_vec:
                    # 간단 코사인 (pure python)
                    def _cos(a: list[float], b: list[float]) -> float:
                        dot = 0.0
                        na = 0.0
                        nb = 0.0
                        for x, y in zip(a, b):
                            dot += x * y
                            na += x * x
                            nb += y * y
                        if na <= 0.0 or nb <= 0.0:
                            return 0.0
                        return dot / ((na ** 0.5) * (nb ** 0.5))

                    best: Optional[tuple[int, str, float]] = None
                    for qc in qcs:
                        name = str(qc.get("name", "") or "")
                        desc = str(qc.get("description", "") or "")
                        c_text = (name + "\n" + desc).strip()
                        c_vec = text_to_vector(c_text)
                        if not c_vec:
                            continue
                        score = _cos(q_vec, c_vec)
                        if best is None or score > best[2]:
                            best = (int(qc["id"]), name, float(score))

                    # threshold는 임시값(운영 중 튜닝)
                    if best and best[2] >= float(getattr(config, "CHAT_CATEGORY_MIN_SCORE", 0.75)):
                        return best[0], best[1]
            except Exception:
                log.exception("quick_category embedding classify failed")

    # 3) LLM 분류(라벨 제한) - 아직 연결 안 함(필요해지면 추가)
    # -> fallback

    if etc_id is not None:
        return etc_id, etc_name or "etc"
    return None, None


def _record_user_message_and_update_insights(
    db: Session,
    *,
    session_id: int,
    content: str,
    channel: Optional[str],
    extra_data: dict,
) -> None:
    """
    Tx(짧게): user message 저장 + message_insight(keywords) 저장 + session_insight(first/qcount/category) 업데이트
    - LLM 호출은 절대 여기서 하지 않음.
    """
    # 1) message
    msg = crud_chat.create_message(
        db,
        session_id=session_id,
        role="user",
        content=content,
        vector_memory=None,
        response_latency_ms=None,
        extra_data=extra_data,
        commit=False,
        refresh=True,
    )

    # 2) keywords
    keywords = _extract_keywords_simple(content)

    # 3) message_insight
    crud_chat_history.upsert_message_insight(
        db,
        message_id=getattr(msg, "id", None) or getattr(msg, "message_id"),
        session_id=session_id,
        is_question=True,
        category=None,
        keywords=keywords,
        created_at=msg.created_at,
    )

    # 4) session_insight
    ins = crud_chat_history.ensure_session_insight(db, session_id=session_id)

    normalized_channel = _normalize_channel(channel)
    # channel은 최초 1회만 세팅(있으면 유지)
    if normalized_channel and not getattr(ins, "channel", None):
        ins.channel = str(normalized_channel)

    # question_count는 user 질문마다 +1
    current_q = int(getattr(ins, "question_count", 0) or 0)
    ins.question_count = current_q + 1

    # first_question은 최초 1회만
    if not getattr(ins, "first_question", None):
        ins.first_question = content

    # category는 최초 1회만 확정(quick_category_id가 비어 있을 때)
    if getattr(ins, "quick_category_id", None) is None:
        qc_id, qc_name = _classify_quick_category(db, text=content, keywords=keywords)
        if qc_id is not None:
            ins.quick_category_id = int(qc_id)
        # 캐시용 name(선택)
        if qc_name:
            ins.category = str(qc_name)

    db.add(ins)
    db.flush()


def ask_in_session_service(db: Session, *, session_id: int, payload: ChatQARequest) -> QAResponse:
    _ensure_session(db, session_id)

    if getattr(payload, "role", "user") != "user":
        raise HTTPException(status_code=400, detail="role must be 'user'")

    flags = _extract_policy_flags(payload)
    few_shot_profile: str = str(getattr(payload, "few_shot_profile", None) or "support_md")

    # 운영 규칙: channel은 web/mobile 고정 코드로 저장(없으면 web 기본값)
    channel: Optional[str] = getattr(payload, "channel", None)
    channel = _normalize_channel(channel)

    # Tx1) user message + insights (LLM 호출 전에 커밋되어야 runner가 히스토리 조회 가능)
    try:
        _record_user_message_and_update_insights(
            db,
            session_id=session_id,
            content=payload.question,
            channel=channel,
            extra_data={
                "knowledge_id": payload.knowledge_id,
                "top_k": payload.top_k,
                "style": payload.style,
                "policy_flags": flags,
                "few_shot_profile": few_shot_profile,
                "source": "text",
                "channel": channel,
            },
        )
        db.commit()
    except Exception:
        db.rollback()
        raise

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

    # Tx2) assistant message 기록
    try:
        msg = crud_chat.create_message(
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
                    "channel": channel,
                    "status": resp.status,
                    "reason_code": resp.reason_code,
                    "retrieval_meta": getattr(resp, "retrieval_meta", None),
                    "citations": [c.model_dump() for c in resp.citations],
                }
            ),
            commit=False,   # 여기서 바로 커밋하지 않고
            refresh=True,
        )
        if resp.status != "ok":
            ins = crud_chat_history.ensure_session_insight(db, session_id=session_id)
            ins.status = "failed"
            ins.failed_reason = resp.answer[:200]
            db.add(ins)
            _record_failure_suggestion(
                db,
                session_id=session_id,
                question_text=payload.question,
                assistant_message=msg,
                resp=resp,
            )
        db.commit()        # 함수 레벨에서 확정
    except Exception:
        db.rollback()
        raise

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

    # 세션이 있으면 ask_in_session과 동일하게 로그 남김 (+ insights)
    if session_id is not None:
        with db.begin():
            _record_user_message_and_update_insights(
                db,
                session_id=session_id,
                content=text,
                channel=None,  # STT endpoint에 channel 입력이 없어서 None 유지 (필요하면 endpoint에 Form 필드로 추가)
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
        with db.begin():
            msg = crud_chat.create_message(
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
                        "status": resp.status,
                        "reason_code": resp.reason_code,
                        "retrieval_meta": getattr(resp, "retrieval_meta", None),
                        "citations": [c.model_dump() for c in resp.citations],
                    }
                ),
                commit=False,
                refresh=True,
            )
            if resp.status != "ok":
                ins = crud_chat_history.ensure_session_insight(db, session_id=session_id)
                ins.status = "failed"
                ins.failed_reason = resp.answer[:200]
                db.add(ins)
                _record_failure_suggestion(
                    db,
                    session_id=session_id,
                    question_text=text,
                    assistant_message=msg,
                    resp=resp,
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
