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
    description=(
        "세션 인사이트 목록을 조회(null 제외)\n"
        "- 기간(date_from/date_to), 상태(status), 채널(channel), 카테고리(category), 대분류(quick_category_id)로 필터링\n"
        "- q는 first_question/failed_reason 부분검색\n"
        "- offset/limit 페이징 지원"
    ),
)
def list_sessions(
    date_from: Optional[date] = Query(None, description="시작일(YYYY-MM-DD). 생략 시 전체"),
    date_to: Optional[date] = Query(None, description="종료일(YYYY-MM-DD). 생략 시 전체"),
    status: Optional[ChatInsightStatus] = Query(None, description="세션 인사이트 상태(success/failed)"),
    channel: Optional[ChannelLiteral] = Query(None, description="채널 코드(web/mobile 등)"),
    category: Optional[str] = Query(None, description="세션 카테고리(문자열)"),
    quick_category_id: Optional[int] = Query(None, ge=1, description="quick_category.id(대분류)"),
    q: Optional[str] = Query(None, description="first_question/failed_reason 부분검색"),
    offset: int = Query(0, ge=0, description="페이징 offset"),
    limit: int = Query(50, ge=1, le=200, description="페이징 limit(최대 200)"),
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
    description=(
        "세션 인사이트 카운트를 반환\n"
        "- 동일한 필터(기간/채널/카테고리/대분류) 조건으로 total/success/failed를 집계"
    ),
)
def count_sessions(
    date_from: Optional[date] = Query(None, description="시작일(YYYY-MM-DD). 생략 시 전체"),
    date_to: Optional[date] = Query(None, description="종료일(YYYY-MM-DD). 생략 시 전체"),
    channel: Optional[ChannelLiteral] = Query(None, description="채널 코드(web/mobile 등)"),
    category: Optional[str] = Query(None, description="세션 카테고리(문자열)"),
    quick_category_id: Optional[int] = Query(None, ge=1, description="quick_category.id(대분류)"),
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
    description=(
        "질문(=user role 메시지) 인사이트 목록을 조회합니다.\n"
        "- 기간/세션/채널/카테고리 조건으로 필터링\n"
        "- 내부적으로 message_insight 중 is_question=true만 반환"
    ),
)
def list_questions(
    date_from: Optional[date] = Query(None, description="시작일(YYYY-MM-DD). 생략 시 전체"),
    date_to: Optional[date] = Query(None, description="종료일(YYYY-MM-DD). 생략 시 전체"),
    session_id: Optional[int] = Query(None, description="특정 세션만 조회할 때 session_id"),
    channel: Optional[ChannelLiteral] = Query(None, description="채널 코드(web/mobile 등)"),
    category: Optional[str] = Query(None, description="메시지/세션 카테고리(문자열)"),
    offset: int = Query(0, ge=0, description="페이징 offset"),
    limit: int = Query(50, ge=1, le=200, description="페이징 limit(최대 200)"),
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
    description=(
        "기간 내 키워드 상위 Top N 집계를 반환.\n"
        "- channel/quick_category_id 조건으로 분리된 워드클라우드 생성에 사용\n"
        "- 응답: [{keyword, count}, ...]"
    ),
)
def wordcloud(
    date_from: Optional[date] = Query(None, description="시작일(YYYY-MM-DD). 생략 시 전체"),
    date_to: Optional[date] = Query(None, description="종료일(YYYY-MM-DD). 생략 시 전체"),
    channel: Optional[ChannelLiteral] = Query(None, description="채널 코드(web/mobile 등)"),
    quick_category_id: Optional[int] = Query(None, ge=1, description="quick_category.id(대분류)"),
    top_n: int = Query(100, ge=1, le=500, description="상위 N개(최대 500)"),
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
    summary="대화기록: 기간 재집계(트리거)",
    description=(
        "지정한 기간(date_from~date_to)의 인사이트/키워드 집계를 재생성\n"
        "- 대량 데이터 수정/백필(backfill) 후 재집계 용도\n"
        "- 비동기 작업처럼 202(ACCEPTED)로 응답하지만, 구현에 따라 동기 처리도 가능"
    ),
)
def rebuild(
    date_from: date = Query(..., description="시작일(YYYY-MM-DD)"),
    date_to: date = Query(..., description="종료일(YYYY-MM-DD)"),
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
    description=(
        "실패/리뷰 대상(knowledge_suggestion) 목록을 조회\n"
        "- review_status(pending/ingested/deleted), answer_status(error/...), 세션/채널/기간 필터\n"
        "- 운영자가 pending을 골라 ingest 또는 delete 처리하는 화면에 사용"
    ),
)
def list_suggestions(
    date_from: Optional[date] = Query(None, description="시작일(YYYY-MM-DD). 생략 시 전체"),
    date_to: Optional[date] = Query(None, description="종료일(YYYY-MM-DD). 생략 시 전체"),
    review_status: Optional[ReviewStatus] = Query(None, description="리뷰 상태(pending/ingested/deleted)"),
    answer_status: Optional[AnswerStatus] = Query(None, description="답변 상태(error/...)"),
    session_id: Optional[int] = Query(None, description="특정 세션만 조회할 때 session_id"),
    channel: Optional[ChannelLiteral] = Query(None, description="채널 코드(web/mobile 등)"),
    offset: int = Query(0, ge=0, description="페이징 offset"),
    limit: int = Query(50, ge=1, le=200, description="페이징 limit(최대 200)"),
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
    description=(
        "실패/리뷰 큐의 상태별 카운트를 반환\n"
        "- 필터(기간/세션/채널/answer_status)를 동일하게 적용한 뒤\n"
        "  total/pending/ingested/deleted로 분해해서 반환"
    ),
)
def count_suggestions(
    date_from: Optional[date] = Query(None, description="시작일(YYYY-MM-DD). 생략 시 전체"),
    date_to: Optional[date] = Query(None, description="종료일(YYYY-MM-DD). 생략 시 전체"),
    answer_status: Optional[AnswerStatus] = Query(None, description="답변 상태(error/...)"),
    session_id: Optional[int] = Query(None, description="특정 세션만 조회할 때 session_id"),
    channel: Optional[ChannelLiteral] = Query(None, description="채널 코드(web/mobile 등)"),
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
    description=(
        "pending 상태의 knowledge_suggestion을 생성하거나(없으면), 동일 message_id 기준으로 갱신(멱등).\n"
        "- 운영/자동화 로직에서 '실패 케이스 적재' 용도로 호출\n"
        "- 최소 입력: session_id, message_id, question_text, assistant_answer(또는 빈값), reason_code"
    ),
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
    description=(
        "pending suggestion을 지식베이스에 반영하고 ingested로 전환\n"
        "- final_answer는 필수(운영자 확정 답변)\n"
        "- target_knowledge_id 우선순위: payload > suggestion.target_knowledge_id > ENV 기본값\n"
        "- 저장 텍스트는 'Q: ...\\nA: ...' 형태로 chunk 생성(검색 힌트 강화)\n"
        "- 임베딩 생성이 실패해도 chunk는 저장되도록 설계(벡터는 None/기본값 처리)"
    ),
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

    chunk_text = f"Q: {sug.question_text}\nA: {final_answer}"

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
    description=(
        "pending suggestion을 deleted 상태로 전환\n"
        "- 운영자 판단으로 반영하지 않기로 결정한 케이스 처리\n"
        "- 이미 ingested인 항목은 정책상 제한될 수 있으며(ValueError) 400으로 반환"
    ),
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
    description=(
        "message 레코드를 하드 삭제\n"
        "- 연관 테이블이 FK CASCADE로 연결돼 있으면 관련 인사이트/제안/첨부 데이터가 함께 삭제\n"
        "- 운영 환경에서는 데이터 정합성/감사 로그 정책을 고려해서 신중히 사용"
    ),
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
