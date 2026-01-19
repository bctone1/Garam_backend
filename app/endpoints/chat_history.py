# app/endpoints/chat_history.py
from __future__ import annotations

import os
from datetime import date
from typing import Optional, List, Dict, Any

from fastapi import APIRouter, Depends, HTTPException, Query, status as http_status
from sqlalchemy.orm import Session

from database.session import get_db

from schemas.chat_history import (
    # literals
    ChatInsightStatus,
    ChannelLiteral,
    AnswerStatus,
    ReviewStatus,

    # existing
    ChatSessionInsightResponse,
    ChatMessageInsightResponse,
    WordCloudResponse,

    # suggestion
    KnowledgeSuggestionResponse,
    KnowledgeSuggestionCreate,
    KnowledgeSuggestionIngestRequest,
    KnowledgeSuggestionDeleteRequest,
)

from crud import chat_history as crud
from crud import knowledge as knowledge_crud

from models.chat import Message
from service import chat_history as svc

router = APIRouter(prefix="/chat-history", tags=["대화 기록"])


@router.get(
    "/sessions",
    response_model=List[ChatSessionInsightResponse],
    summary="대화기록: 세션 요약/분류 목록",
)
def list_sessions(
    date_from: Optional[date] = Query(None),
    date_to: Optional[date] = Query(None),
    status: Optional[ChatInsightStatus] = Query(None),  # success/failed
    channel: Optional[ChannelLiteral] = Query(None),
    category: Optional[str] = Query(None),
    quick_category_id: Optional[int] = Query(None, ge=1),
    q: Optional[str] = Query(None),
    offset: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=200),
    db: Session = Depends(get_db),
):
    return crud.list_session_insights(
        db,
        date_from=date_from,
        date_to=date_to,
        status=status,
        channel=channel,
        category=category,
        quick_category_id=quick_category_id,
        q=q,
        offset=offset,
        limit=limit,
    )


@router.get(
    "/sessions/count",
    response_model=Dict[str, int],
    summary="대화기록: 세션 카운트(전체/성공/실패)",
)
def count_sessions(
    date_from: Optional[date] = Query(None),
    date_to: Optional[date] = Query(None),
    channel: Optional[ChannelLiteral] = Query(None),
    category: Optional[str] = Query(None),
    quick_category_id: Optional[int] = Query(None, ge=1),
    db: Session = Depends(get_db),
):
    total = crud.count_session_insights(
        db,
        date_from=date_from,
        date_to=date_to,
        status=None,
        channel=channel,
        category=category,
        quick_category_id=quick_category_id,
    )
    failed = crud.count_session_insights(
        db,
        date_from=date_from,
        date_to=date_to,
        status="failed",
        channel=channel,
        category=category,
        quick_category_id=quick_category_id,
    )
    return {"total": total, "success": total - failed, "failed": failed}


@router.get(
    "/questions",
    response_model=List[ChatMessageInsightResponse],
    summary="대화기록: 질문(=user 메시지) 목록",
)
def list_questions(
    date_from: Optional[date] = Query(None),
    date_to: Optional[date] = Query(None),
    session_id: Optional[int] = Query(None),
    channel: Optional[ChannelLiteral] = Query(None),
    category: Optional[str] = Query(None),
    offset: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=200),
    db: Session = Depends(get_db),
):
    items = crud.list_message_insights(
        db,
        date_from=date_from,
        date_to=date_to,
        session_id=session_id,
        channel=channel,
        category=category,
        offset=offset,
        limit=limit,
    )
    return [x for x in items if bool(getattr(x, "is_question", False))]


@router.get(
    "/wordcloud",
    response_model=WordCloudResponse,
    summary="대화기록: 워드클라우드(키워드 Top N)",
)
def wordcloud(
    date_from: Optional[date] = Query(None),
    date_to: Optional[date] = Query(None),
    channel: Optional[ChannelLiteral] = Query(None),
    quick_category_id: Optional[int] = Query(None, ge=1),
    top_n: int = Query(100, ge=1, le=500),
    db: Session = Depends(get_db),
):
    rows = crud.list_keyword_daily(
        db,
        date_from=date_from,
        date_to=date_to,
        channel=channel,
        quick_category_id=quick_category_id,
        top_n=top_n,
    )
    return WordCloudResponse(items=[{"keyword": r.keyword, "count": int(r.count)} for r in rows])


@router.post(
    "/rebuild",
    status_code=http_status.HTTP_202_ACCEPTED,
    response_model=Dict[str, Any],
    summary="대화기록: 기간 재집계(인사이트/키워드)",
)
def rebuild(
    date_from: date = Query(...),
    date_to: date = Query(...),
    db: Session = Depends(get_db),
):
    if date_from > date_to:
        raise HTTPException(status_code=400, detail="date_from must be <= date_to")
    return svc.rebuild_range(db, date_from=date_from, date_to=date_to)


# =========================================================
# knowledge_suggestion endpoints
# =========================================================
def _default_target_knowledge_id() -> Optional[int]:
    for key in ("KNOWLEDGE_SUGGESTION_DEFAULT_KNOWLEDGE_ID", "FAILURE_KNOWLEDGE_ID"):
        v = os.getenv(key)
        if v:
            try:
                return int(v)
            except Exception:
                return None
    return None


@router.get(
    "/suggestions",
    response_model=List[KnowledgeSuggestionResponse],
    summary="실패/리뷰 큐: 목록",
)
def list_suggestions(
    date_from: Optional[date] = Query(None),
    date_to: Optional[date] = Query(None),
    review_status: Optional[ReviewStatus] = Query(None),
    answer_status: Optional[AnswerStatus] = Query(None),
    session_id: Optional[int] = Query(None),
    channel: Optional[ChannelLiteral] = Query(None),
    offset: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=200),
    db: Session = Depends(get_db),
):
    return crud.list_knowledge_suggestions(
        db,
        date_from=date_from,
        date_to=date_to,
        review_status=review_status,
        answer_status=answer_status,
        session_id=session_id,
        channel=channel,
        offset=offset,
        limit=limit,
    )


@router.get(
    "/suggestions/count",
    response_model=Dict[str, int],
    summary="실패/리뷰 큐: 카운트(total/pending/ingested/deleted)",
)
def count_suggestions(
    date_from: Optional[date] = Query(None),
    date_to: Optional[date] = Query(None),
    answer_status: Optional[AnswerStatus] = Query(None),
    session_id: Optional[int] = Query(None),
    channel: Optional[ChannelLiteral] = Query(None),
    db: Session = Depends(get_db),
):
    total = crud.count_knowledge_suggestions(
        db,
        date_from=date_from,
        date_to=date_to,
        review_status=None,
        answer_status=answer_status,
        session_id=session_id,
        channel=channel,
    )
    pending = crud.count_knowledge_suggestions(
        db,
        date_from=date_from,
        date_to=date_to,
        review_status="pending",
        answer_status=answer_status,
        session_id=session_id,
        channel=channel,
    )
    ingested = crud.count_knowledge_suggestions(
        db,
        date_from=date_from,
        date_to=date_to,
        review_status="ingested",
        answer_status=answer_status,
        session_id=session_id,
        channel=channel,
    )
    deleted = crud.count_knowledge_suggestions(
        db,
        date_from=date_from,
        date_to=date_to,
        review_status="deleted",
        answer_status=answer_status,
        session_id=session_id,
        channel=channel,
    )
    return {"total": total, "pending": pending, "ingested": ingested, "deleted": deleted}


@router.post(
    "/suggestions/pending",
    response_model=KnowledgeSuggestionResponse,
    status_code=http_status.HTTP_201_CREATED,
    summary="실패/리뷰 큐: pending 생성(또는 멱등 upsert)",
)
def create_pending_suggestion(
    payload: KnowledgeSuggestionCreate,
    db: Session = Depends(get_db),
):
    obj = crud.upsert_pending_knowledge_suggestion(
        db,
        session_id=payload.session_id,
        message_id=payload.message_id,
        question_text=payload.question_text,
        assistant_answer=payload.assistant_answer,
        reason_code=payload.reason_code,
        retrieval_meta=payload.retrieval_meta,
        answer_status="error",
    )
    db.commit()
    db.refresh(obj)
    return obj


@router.post(
    "/suggestions/{message_id}/ingest",
    response_model=KnowledgeSuggestionResponse,
    summary="실패/리뷰 큐: 지식베이스 반영(pending -> ingested)",
)
def ingest_suggestion(
    message_id: int,
    payload: KnowledgeSuggestionIngestRequest,
    db: Session = Depends(get_db),
):
    sug = crud.get_knowledge_suggestion_by_message(db, message_id)
    if not sug:
        raise HTTPException(status_code=404, detail="knowledge_suggestion not found")

    if sug.review_status == "ingested":
        return sug
    if sug.review_status == "deleted":
        raise HTTPException(status_code=400, detail="cannot ingest a deleted suggestion")

    target_id = payload.target_knowledge_id or sug.target_knowledge_id or _default_target_knowledge_id()
    if not target_id:
        raise HTTPException(
            status_code=400,
            detail="target_knowledge_id required (or set env KNOWLEDGE_SUGGESTION_DEFAULT_KNOWLEDGE_ID)",
        )

    final_answer = payload.final_answer.strip()
    if not final_answer:
        raise HTTPException(status_code=400, detail="final_answer required")

    # chunk 텍스트: Q/A 같이 넣어서 검색 힌트 강화
    chunk_text = f"Q: {sug.question_text}\nA: {final_answer}"

    # (선택) 임베딩. 실패해도 동작은 하게(제로 벡터 fallback)
    vector = None
    try:
        from langchain_service.embedding.get_vector import text_to_vector  # type: ignore
        vector = text_to_vector(chunk_text)
    except Exception:
        vector = None


    chunk_index = 1_000_000_000 + int(message_id)

    chunk = knowledge_crud.upsert_chunk_with_default_vector(
        db,
        knowledge_id=int(target_id),
        page_id=None,
        chunk_index=int(chunk_index),
        chunk_text=chunk_text,
        vector_memory=vector,
        vector_dim=1536,
    )

    obj = crud.mark_knowledge_suggestion_ingested(
        db,
        message_id=message_id,
        final_answer=final_answer,
        target_knowledge_id=int(target_id),
        ingested_chunk_id=int(chunk.id),
    )
    db.commit()
    db.refresh(obj)
    return obj


@router.post(
    "/suggestions/{message_id}/delete",
    response_model=KnowledgeSuggestionResponse,
    summary="실패/리뷰 큐: 삭제 처리(pending -> deleted)",
)
def delete_suggestion(
    message_id: int,
    payload: KnowledgeSuggestionDeleteRequest,
    db: Session = Depends(get_db),
):
    try:
        obj = crud.mark_knowledge_suggestion_deleted(db, message_id=message_id)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    db.commit()
    db.refresh(obj)
    return obj


@router.delete(
    "/messages/{message_id}",
    status_code=http_status.HTTP_204_NO_CONTENT,
    summary="대화기록: 메시지 하드 삭제(원하면 사용, FK는 CASCADE로 같이 삭제됨)",
)
def hard_delete_message(
    message_id: int,
    db: Session = Depends(get_db),
):
    msg = db.get(Message, message_id)
    if not msg:
        return
    db.delete(msg)
    db.commit()
    return
