# langchain_service/llm/runner.py
from __future__ import annotations

import os
import re
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

from service.knowledge_retrieval import retrieve_topk_hybrid_with_scores

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
) -> Tuple[List[QASource], str, dict[str, Any]]:
    chunks, score_map, max_sim = retrieve_topk_hybrid_with_scores(
        db,
        query_vector=vector,
        knowledge_id=knowledge_id,
        top_k=top_k,
        query_text=question,
    )

    sources: List[QASource] = []
    context_lines: list[str] = []
    for c in chunks:
        cid = getattr(c, "id", None)
        kid = getattr(c, "knowledge_id", None)
        pid = getattr(c, "page_id", None)
        score = None
        if cid is not None and int(cid) in score_map:
            score = score_map[int(cid)].get("sim")
        score_repr = f"{float(score):.4f}" if score is not None else "null"
        context_lines.append(
            f"[CHUNK id={cid} knowledge_id={kid} page_id={pid} score={score_repr}]"
        )
        chunk_text = getattr(c, "chunk_text", "") or ""
        context_lines.append(chunk_text)
        sources.append(
            QASource(
                chunk_id=cid,
                knowledge_id=kid,
                page_id=pid,
                chunk_index=getattr(c, "chunk_index", None),
                text=chunk_text,
            )
        )

    context_text = ("\n\n".join(context_lines))[:MAX_CTX_CHARS]
    meta = {"max_sim": max_sim, "has_chunks": bool(chunks)}
    return sources, context_text, meta


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
        "Refer to the following context.",
        "[Context Start]",
        context_text,
        "[Context End]",
        "Question: " + question,
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
    sources, context_text, meta = _retrieve_sources_and_context(
        db,
        vector=vector,
        knowledge_id=knowledge_id,
        top_k=top_k,
        question=question,
    )

    min_score = float(getattr(config, "RAG_MIN_SCORE", 0.12))
    max_sim = meta.get("max_sim")
    if not meta.get("has_chunks") or (max_sim is not None and float(max_sim) < min_score):
        return QAResponse(
            status="no_knowledge",
            answer="지식베이스에서 근거를 찾지 못했습니다. 질문을 조금 더 구체적으로 알려주세요.",
            reason_code="LOW_RETRIEVAL",
            retrieval_meta=meta,
            citations=[],
            question=question,
            session_id=session_id,
            sources=[],
            documents=[],
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

    status_val = "no_knowledge"
    reason_code = "MISSING_METADATA"
    citations: list[dict[str, Any]] = []
    answer_val = resp_text or ""
    has_metadata = False

    meta_match = re.search(r"<!--(.*?)-->\s*$", resp_text or "", flags=re.DOTALL)
    if meta_match:
        has_metadata = True
        meta_block = meta_match.group(1)
        answer_val = (resp_text or "")[: meta_match.start()].strip()
        for raw_line in meta_block.splitlines():
            line = raw_line.strip()
            if not line or ":" not in line:
                continue
            key, val = [p.strip() for p in line.split(":", 1)]
            key_upper = key.upper()
            if key_upper == "STATUS":
                status_val = val
            elif key_upper == "REASON_CODE":
                reason_code = val or None
            elif key_upper == "CITATIONS":
                items = [v.strip() for v in val.split("|") if v.strip()]
                for item in items:
                    entry: dict[str, Any] = {}
                    for part in item.split(","):
                        if "=" not in part:
                            continue
                        k, v = [p.strip() for p in part.split("=", 1)]
                        if k in {"chunk_id", "knowledge_id", "page_id"}:
                            try:
                                entry[k] = int(v)
                            except Exception:
                                continue
                        elif k == "score":
                            try:
                                entry[k] = float(v)
                            except Exception:
                                continue
                    if entry:
                        citations.append(entry)

    if not has_metadata and sources:
        status_val = "ok"
        reason_code = reason_code or "MISSING_METADATA"
        citations = [
            {
                "chunk_id": getattr(sources[0], "chunk_id", None),
                "knowledge_id": getattr(sources[0], "knowledge_id", None),
                "page_id": getattr(sources[0], "page_id", None),
                "score": None,
            }
        ]

    if status_val not in {"ok", "no_knowledge", "need_clarification"}:
        status_val = "no_knowledge"
        reason_code = reason_code or "INVALID_METADATA"

    if status_val == "ok" and not citations and sources:
        citations = [
            {
                "chunk_id": getattr(sources[0], "chunk_id", None),
                "knowledge_id": getattr(sources[0], "knowledge_id", None),
                "page_id": getattr(sources[0], "page_id", None),
                "score": None,
            }
        ]
        reason_code = reason_code or "MISSING_CITATION"
    elif status_val == "ok" and not citations:
        status_val = "no_knowledge"
        reason_code = reason_code or "MISSING_CITATION"

    if status_val != "ok":
        if status_val == "need_clarification":
            answer_val = "질문을 조금 더 구체적으로 알려주세요."
        else:
            answer_val = "지식베이스에서 근거를 찾지 못했습니다. 질문을 조금 더 구체적으로 알려주세요."

    source_map = {int(getattr(s, "chunk_id", 0) or 0): s for s in sources}
    resolved_sources: list[QASource] = []
    for item in citations:
        cid = item.get("chunk_id")
        if isinstance(cid, int) and cid in source_map:
            resolved_sources.append(source_map[cid])

    return QAResponse(
        status=status_val,
        answer=str(answer_val or ""),
        reason_code=reason_code,
        retrieval_meta=meta,
        citations=citations,
        question=question,
        session_id=session_id,
        sources=resolved_sources,
        documents=resolved_sources,
    )
