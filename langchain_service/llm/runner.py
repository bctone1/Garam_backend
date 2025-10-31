# langchain_service/llm/runner.py
from __future__ import annotations

from typing import Iterable, Optional
import logging
from datetime import datetime, timezone
from decimal import Decimal
from fastapi import HTTPException, status
from sqlalchemy.orm import Session

from crud import chat as crud_chat
from crud import knowledge as crud_knowledge
from crud import api_cost as crud_cost

from schemas.llm import QASource, QAResponse

from core import config
from core.pricing import (
    tokens_for_texts,
    estimate_llm_cost_usd,
)

from langchain_service.chain.qa_chain import make_qa_chain
from langchain_service.embedding.get_vector import text_to_vector, _to_vector
from langchain_service.llm.setup import get_llm
try:
    from langchain_community.callbacks import get_openai_callback
except Exception:
    get_openai_callback = None


log = logging.getLogger("api_cost")


def _update_last_user_vector(db: Session, session_id: int, vector: Iterable[float]) -> None:
    message = crud_chat.last_by_role(db, session_id, "user")
    if not message:
        return
    message.vector_memory = list(vector)
    db.add(message)
    db.commit()
    db.refresh(message)


def _build_sources(db: Session, vector: list[float], knowledge_id: Optional[int], top_k: int) -> list[QASource]:
    chunks = crud_knowledge.search_chunks_by_vector(
        db,
        query_vector=vector,
        knowledge_id=knowledge_id,
        top_k=top_k,
    )
    return [
        QASource(
            chunk_id=chunk.id,
            knowledge_id=chunk.knowledge_id,
            page_id=chunk.page_id,
            chunk_index=chunk.chunk_index,
            text=chunk.chunk_text,
        )
        for chunk in chunks
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
) -> QAResponse:
    vector = _to_vector(question)
    if session_id is not None:
        _update_last_user_vector(db, session_id, vector)

    try:
        chain = make_qa_chain(
            db,
            get_llm,
            text_to_vector,
            knowledge_id=knowledge_id,
            top_k=top_k,
            policy_flags=policy_flags or {},
            style=style or "friendly",
            streaming=True,
        )
    except RuntimeError as exc:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc)) from exc

    # 실제 호출 및 비용 집계
    provider = getattr(config, "LLM_PROVIDER", "openai")
    model = getattr(config, "LLM_MODEL", getattr(config, "DEFAULT_CHAT_MODEL", "gpt-4o-mini"))

    try:
        if (provider == "openai") and (get_openai_callback is not None):
            # 정확 집계 경로
            with get_openai_callback() as cb:
                raw = chain.invoke({"question": question})
                prompt_toks = int(getattr(cb, "prompt_tokens", 0) or 0)
                completion_toks = int(getattr(cb, "completion_tokens", 0) or 0)
                total_tokens = int(getattr(cb, "total_tokens", prompt_toks + completion_toks) or 0)
                # cb.total_cost는 float. Decimal로 변환해 저장 안정성 확보
                usd = Decimal(str(getattr(cb, "total_cost", 0.0) or 0.0))

            log.info(
                "api-cost(openai): prompt=%d completion=%d total=%d usd=%s model=%s",
                prompt_toks, completion_toks, total_tokens, usd, model
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
            # Fallback: 추정 계산
            raw = chain.invoke({"question": question})

            try:
                resp_text = str(raw)
                total_tokens = tokens_for_texts(model, [question, resp_text])
                usd = estimate_llm_cost_usd(model=model, total_tokens=total_tokens)
                log.info("api-cost(fallback): tokens=%d usd=%s model=%s", total_tokens, usd, model)
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
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="LLM 호출에 실패했습니다."
        ) from exc

    sources = _build_sources(db, vector, knowledge_id, top_k)
    return QAResponse(
        answer=str(raw),
        question=question,
        session_id=session_id,
        sources=sources,
        documents=sources,
    )
