# langchain_service/llm/runner.py
from __future__ import annotations
import os
from typing import Iterable, Optional, Tuple, List, Any
import logging
from datetime import datetime, timezone
from decimal import Decimal
import json

from fastapi import HTTPException, status
from sqlalchemy.orm import Session

from crud import chat as crud_chat
from crud import api_cost as crud_cost
from crud import model as crud_model

from schemas.llm import QASource, QAResponse

from core import config
from core.pricing import tokens_for_texts, estimate_llm_cost_usd

from service.knowledge_retrieval import retrieve_topk_hybrid

from langchain_service.chain.qa_chain import make_qa_chain
from langchain_service.embedding.get_vector import _to_vector
from langchain_service.llm.setup import get_llm
from langchain_service.prompt.style import build_system_prompt
from langchain_service.prompt.few_shots import load_few_shot_profile

try:
    from langchain_community.callbacks import get_openai_callback
except Exception:
    try:
        from langchain_community.callbacks.manager import get_openai_callback  # 일부 버전
    except Exception:
        get_openai_callback = None

log = logging.getLogger("api_cost")

MAX_CTX_CHARS = 12000  # qa_chain 기본값과 동일


def _update_last_user_vector(db: Session, session_id: int, vector: Iterable[float]) -> None:
    message = crud_chat.last_by_role(db, session_id, "user")
    if not message:
        return
    message.vector_memory = list(vector)
    db.add(message)
    db.commit()
    db.refresh(message)


def _retrieve_sources_and_context(
    db: Session,
    *,
    vector: list[float],
    knowledge_id: Optional[int],
    top_k: int,
    question: str,
) -> Tuple[List[QASource], str]:
    """
    검색 1회로 sources + context_text를 같이 만든다.
    (qa_chain과 동일하게 hybrid 검색 사용)
    """
    chunks = retrieve_topk_hybrid(
        db,
        query_vector=vector,
        knowledge_id=knowledge_id,
        top_k=top_k,
        query_text=question,
    )

    sources: List[QASource] = []
    for c in chunks:
        sources.append(
            QASource(
                chunk_id=getattr(c, "id", None),
                knowledge_id=getattr(c, "knowledge_id", None),
                page_id=getattr(c, "page_id", None),
                chunk_index=getattr(c, "chunk_index", None),
                text=getattr(c, "chunk_text", "") or "",
            )
        )

    context_text = ("\n\n".join(s.text for s in sources))[:MAX_CTX_CHARS]
    return sources, context_text


def _load_profile_for_prompt(name: str) -> Optional[dict]:
    # 파일명 오타/버전 대비 fallback
    for cand in [name, "support_v1", "support_v1"]:
        try:
            return load_few_shot_profile(cand)
        except FileNotFoundError:
            continue
        except Exception:
            continue
    return None


def _render_prompt_for_estimate(
    *,
    question: str,
    context_text: str,
    style: Optional[str],
    policy_flags: Optional[dict],
    force_json_output: bool,
    few_shot_profile: str,
) -> list[str]:
    """
    tokens_for_texts()에 전달할 '조각 리스트' 반환.
    JSON 계약/규칙 + few-shot까지 포함해서 추정 정확도 올림.
    """
    system_txt = build_system_prompt(style=(style or "friendly"), **(policy_flags or {}))

    parts: list[str] = [system_txt]

    if force_json_output:
        prof = _load_profile_for_prompt(few_shot_profile)
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

            # few-shot 예시도 토큰에 포함(대충이라도)
            for ex in prof.get("examples", []) or []:
                u = ex.get("user", "")
                a = ex.get("assistant", {})
                parts.append(f"[few-shot user]\n{u}")
                parts.append(f"[few-shot assistant]\n{json.dumps(a, ensure_ascii=False)}")

    # 본문(컨텍스트/질문/라우팅 힌트)
    parts.extend(
        [
            "다음 컨텍스트를 참고해.",
            "[컨텍스트 시작]",
            context_text,
            "[컨텍스트 끝]",
            "질문: " + question,
            # qa_chain에서 force_clarify 라인을 넣으므로, 추정에도 넣어줌(값 자체는 대충 False로)
            "force_clarify: False",
        ]
    )

    return parts


def _extract_json_object(text: str) -> Optional[dict]:
    """
    모델이 앞/뒤에 군더더기 붙여도 JSON 객체만 최대한 뽑아본다.
    """
    if not text:
        return None
    t = text.strip()

    # 1) 그냥 파싱 시도
    try:
        obj = json.loads(t)
        return obj if isinstance(obj, dict) else None
    except Exception:
        pass

    # 2) 첫 '{' ~ 마지막 '}' 구간만 파싱
    i = t.find("{")
    j = t.rfind("}")
    if i >= 0 and j > i:
        candidate = t[i : j + 1]
        try:
            obj = json.loads(candidate)
            return obj if isinstance(obj, dict) else None
        except Exception:
            return None
    return None


def _normalize_contract(obj: dict, raw_text: str) -> dict:
    """
    프론트 파싱 안정성 위해 최소한의 계약 형태로 정규화.
    """
    t = str(obj.get("type") or "").strip().lower()
    if t not in ("answer", "clarify"):
        t = "answer"

    if t == "clarify":
        clarify = obj.get("clarify") if isinstance(obj.get("clarify"), dict) else {}
        options = clarify.get("options") if isinstance(clarify.get("options"), list) else []
        norm_options = []
        for it in options:
            if isinstance(it, dict) and "id" in it and "label" in it:
                norm_options.append({"id": str(it["id"]), "label": str(it["label"])})
        return {
            "type": "clarify",
            "answer": None,
            "clarify": {
                "question": str(clarify.get("question") or "원하시는 내용을 선택해줘."),
                "options": norm_options[:4],
                "required_fields": clarify.get("required_fields") if isinstance(clarify.get("required_fields"), list) else [],
            },
        }

    # answer
    ans = obj.get("answer") if isinstance(obj.get("answer"), dict) else {}
    checks = ans.get("checks") if isinstance(ans.get("checks"), list) else []
    steps = ans.get("steps") if isinstance(ans.get("steps"), list) else []

    summary = ans.get("summary")
    if not summary:
        summary = raw_text.strip()[:500] if raw_text else ""

    return {
        "type": "answer",
        "answer": {
            "summary": str(summary),
            "checks": [str(x) for x in checks][:6],
            "steps": [str(x) for x in steps][:10],
            "fallback": str(ans.get("fallback") or ""),
        },
        "clarify": None,
    }


def _run_qa(
    db: Session,
    *,
    question: str,
    knowledge_id: Optional[int],
    top_k: int,
    session_id: Optional[int] = None,
    policy_flags: Optional[dict] = None,
    style: Optional[str] = None,
    force_json_output: bool = False,
    few_shot_profile: str = "support_v1",
    streaming: bool = False,
) -> QAResponse:
    if style is None:
        m = crud_model.get_single(db)
        if not m:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="model not initialized",
            )
        style = m.response_style

    vector = _to_vector(question)

    if session_id is not None:
        # 기존 함수 그대로 사용
        message = crud_chat.last_by_role(db, session_id, "user")
        if message:
            message.vector_memory = list(vector)
            db.add(message)
            db.commit()
            db.refresh(message)

    # 검색 1회
    chunks = retrieve_topk_hybrid(
        db,
        query_vector=vector,
        knowledge_id=knowledge_id,
        top_k=top_k,
        query_text=question,
    )
    sources = [
        QASource(
            chunk_id=getattr(c, "id", None),
            knowledge_id=getattr(c, "knowledge_id", None),
            page_id=getattr(c, "page_id", None),
            chunk_index=getattr(c, "chunk_index", None),
            text=getattr(c, "chunk_text", "") or "",
        )
        for c in chunks
    ]
    context_text = ("\n\n".join(s.text for s in sources))[:MAX_CTX_CHARS]

    provider = getattr(config, "LLM_PROVIDER", "openai").lower()
    model = getattr(config, "LLM_MODEL", getattr(config, "DEFAULT_CHAT_MODEL", "gpt-4o-mini"))

    raw = ""
    resp_text = ""

    try:
        if provider == "openai" and get_openai_callback is not None:
            with get_openai_callback() as cb:
                chain = make_qa_chain(
                    db,
                    get_llm,
                    _to_vector,  # use_input_context=True라 임베딩/검색 추가 호출 안 됨
                    knowledge_id=knowledge_id,
                    top_k=top_k,
                    policy_flags=policy_flags or {},
                    style=style,
                    streaming=streaming,
                    callbacks=[cb],
                    use_input_context=True,
                    force_json_output=force_json_output,
                    few_shot_profile=few_shot_profile,
                )
                if streaming:
                    raw = "".join(
                        chain.stream(
                            {"question": question, "context": context_text},
                            config={"callbacks": [cb]},
                        )
                    )
                else:
                    raw = chain.invoke(
                        {"question": question, "context": context_text},
                        config={"callbacks": [cb]},
                    )

                resp_text = str(raw or "")

                prompt_parts = _render_prompt_for_estimate(
                    question=question,
                    context_text=context_text,
                    style=style,
                    policy_flags=policy_flags,
                    force_json_output=force_json_output,
                    few_shot_profile=few_shot_profile,
                )
                est_tokens = tokens_for_texts(model, prompt_parts + [resp_text])

                cb_total = int(getattr(cb, "total_tokens", 0) or 0)
                total_tokens = max(cb_total, est_tokens)

                usd_cb = Decimal(str(getattr(cb, "total_cost", 0.0) or 0.0))
                usd_est = estimate_llm_cost_usd(model=model, total_tokens=total_tokens)
                usd = max(usd_cb, usd_est)

                log.info(
                    "api-cost(openai): cb_total=%d est=%d used=%d usd=%s model=%s",
                    cb_total,
                    est_tokens,
                    total_tokens,
                    usd,
                    model,
                )
                try:
                    crud_cost.add_event(
                        db,
                        ts_utc=datetime.now(timezone.utc),
                        product="llm",
                        model=model,
                        llm_tokens=total_tokens,
                        embedding_tokens=0,
                        audio_seconds=0,
                        cost_usd=usd,
                    )
                except Exception as e:
                    log.exception("api-cost llm record failed: %s", e)

        else:
            chain = make_qa_chain(
                db,
                get_llm,
                _to_vector,
                knowledge_id=knowledge_id,
                top_k=top_k,
                policy_flags=policy_flags or {},
                style=style,
                streaming=streaming,
                use_input_context=True,
                force_json_output=force_json_output,
                few_shot_profile=few_shot_profile,
            )
            if streaming:
                raw = "".join(chain.stream({"question": question, "context": context_text}))
            else:
                raw = chain.invoke({"question": question, "context": context_text})

            resp_text = str(raw or "")

            prompt_parts = _render_prompt_for_estimate(
                question=question,
                context_text=context_text,
                style=style,
                policy_flags=policy_flags,
                force_json_output=force_json_output,
                few_shot_profile=few_shot_profile,
            )
            total_tokens = tokens_for_texts(model, prompt_parts + [resp_text])
            usd = estimate_llm_cost_usd(model=model, total_tokens=total_tokens)

            log.info("api-cost(fallback): tokens=%d usd=%s model=%s", total_tokens, usd, model)
            try:
                crud_cost.add_event(
                    db,
                    ts_utc=datetime.now(timezone.utc),
                    product="llm",
                    model=model,
                    llm_tokens=total_tokens,
                    embedding_tokens=0,
                    audio_seconds=0,
                    cost_usd=usd,
                )
            except Exception as e:
                log.exception("api-cost llm record failed: %s", e)

    except Exception as exc:
        log.exception("LLM 호출 실패: provider=%s model=%s err=%r", provider, model, exc)
        detail = "LLM 호출에 실패했습니다."

        if os.getenv("ENV", "").lower() in ("dev", "local") or getattr(config, "DEBUG", False):
            detail = f"{detail} ({type(exc).__name__}: {exc})"

        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=detail,
        ) from exc

    # === JSON 계약 보장: 프론트가 항상 json.loads 가능하도록 ===
    if force_json_output:
        try:
            obj = json.loads(resp_text)
            if not isinstance(obj, dict):
                raise ValueError("not dict")
        except Exception:
            coerced = {
                "type": "answer",
                "answer": {
                    "summary": (resp_text or "")[:500],
                    "checks": [],
                    "steps": [],
                    "fallback": "",
                },
                "clarify": None,
            }
            resp_text = json.dumps(coerced, ensure_ascii=False)

    return QAResponse(
        answer=resp_text,
        question=question,
        session_id=session_id,
        sources=sources,
        documents=sources,
    )
