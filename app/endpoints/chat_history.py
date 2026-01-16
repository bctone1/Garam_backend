# app/endpoints/chat_history.py
from __future__ import annotations

from datetime import date
from typing import Optional, List, Dict, Any

from fastapi import APIRouter, Depends, HTTPException, Query, status as http_status
from sqlalchemy.orm import Session

from database.session import get_db

from schemas.chat_history import (
    ChatSessionInsightResponse,
    ChatMessageInsightResponse,
    WordCloudResponse,
)
from crud import chat_history as crud
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
    status: Optional[str] = Query(None),  # success/failed
    channel: Optional[str] = Query(None),
    # 캐시 필드
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
    channel: Optional[str] = Query(None),
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
    channel: Optional[str] = Query(None),
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
    # 질문만 노출
    return [x for x in items if bool(getattr(x, "is_question", False))]


@router.get(
    "/wordcloud",
    response_model=WordCloudResponse,
    summary="대화기록: 워드클라우드(키워드 Top N)",
)
def wordcloud(
    date_from: Optional[date] = Query(None),
    date_to: Optional[date] = Query(None),
    channel: Optional[str] = Query(None),
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
    return WordCloudResponse(
        items=[{"keyword": r.keyword, "count": int(r.count)} for r in rows]
    )


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
