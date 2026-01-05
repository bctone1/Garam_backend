# langchain_service/llm/runner.py
from __future__ import annotations

import os
import logging
from datetime import datetime, timezone
from decimal import Decimal
from typing import Iterable, Optional, Tuple, List, Any

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
    chunks = retrieve_topk_hybrid(
        db,
        query_vector=vector,
        knowledge_id=knowledge_id,
        top_k=top_k,
        query_text=question,
    )

    sources: List[QASource] = [
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
    return sources, context_text


def _render_prompt_for_estimate(
    *,
    question: str,
    context_text: str,
    style: Optional[str],
    policy_flags: Optional[dict],
) -> list[str]:
    system_txt = build_system_prompt(style=(style or "friendly"), **(policy_flags or {}))
    return [
        system_txt,
        "다음 컨텍스트를 참고해.",
        "[컨텍스트 시작]",
        context_text,
        "[컨텍스트 끝]",
        "질문: " + question,
        "force_clarify: False",
    ]


def _run_qa(
    db: Session,
    *,
    question: str,
    knowledge_id: Optional[int],
    top_k: int,
    session_id: Optional[int] = None,
    policy_flags: Optional[dict] = None,
    style: Optional[str] = None,
    force_json_output: bool = False,         # DEPRECATED: ignored
    few_shot_profile: str = "support_md",    # DEPRECATED: ignored
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
        message = crud_chat.last_by_role(db, session_id, "user")
        if message:
            message.vector_memory = list(vector)
            db.add(message)
            db.commit()
            db.refresh(message)

    # 검색 1회
    sources, context_text = _retrieve_sources_and_context(
        db,
        vector=vector,
        knowledge_id=knowledge_id,
        top_k=top_k,
        question=question,
    )

    provider = getattr(config, "LLM_PROVIDER", "openai").lower()
    model = getattr(config, "LLM_MODEL", getattr(config, "DEFAULT_CHAT_MODEL", "gpt-4o-mini"))

    resp_text = ""

    try:
        if provider == "openai" and get_openai_callback is not None:
            with get_openai_callback() as cb:
                chain = make_qa_chain(
                    db,
                    get_llm,
                    _to_vector,  # use_input_context=True라 추가 검색 안 함
                    knowledge_id=knowledge_id,
                    top_k=top_k,
                    policy_flags=policy_flags or {},
                    style=style,
                    streaming=streaming,
                    callbacks=[cb],
                    use_input_context=True,
                    few_shot_profile=few_shot_profile,
                )

                if streaming:
                    resp_text = "".join(
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
                )
                est_tokens = tokens_for_texts(model, prompt_parts + [resp_text])

                cb_total = int(getattr(cb, "total_tokens", 0) or 0)
                total_tokens = max(cb_total, est_tokens)

                usd_cb = Decimal(str(getattr(cb, "total_cost", 0.0) or 0.0))
                usd_est = estimate_llm_cost_usd(model=model, total_tokens=total_tokens)
                usd = max(usd_cb, usd_est)

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
            )

            if streaming:
                resp_text = "".join(chain.stream({"question": question, "context": context_text}))
            else:
                raw = chain.invoke({"question": question, "context": context_text})
                resp_text = str(raw or "")

            prompt_parts = _render_prompt_for_estimate(
                question=question,
                context_text=context_text,
                style=style,
                policy_flags=policy_flags,
            )
            total_tokens = tokens_for_texts(model, prompt_parts + [resp_text])
            usd = estimate_llm_cost_usd(model=model, total_tokens=total_tokens)

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
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=detail) from exc

    return QAResponse(
        answer=resp_text,
        question=question,
        session_id=session_id,
        sources=sources,
        documents=sources,
    )
