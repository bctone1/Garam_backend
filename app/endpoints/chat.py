# FastAPI 라우터

from __future__ import annotations
from typing import Optional, List
from fastapi import APIRouter, Depends, HTTPException, Query, status, BackgroundTasks
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from service.metrics import recompute_model_metrics
from database.session import get_db, SessionLocal
from crud import chat as crud
from schemas.chat import (
    ChatSessionCreate, ChatSessionUpdate, ChatSessionResponse,
    MessageCreate, MessageResponse,
    FeedbackCreate, FeedbackResponse,
)
router = APIRouter(prefix="/chat", tags=["Chat"])
VECTOR_DIM = 1536


# -------- ChatSession --------
@router.post("/sessions", response_model=ChatSessionResponse, status_code=status.HTTP_201_CREATED)
def create_session(payload: ChatSessionCreate, db: Session = Depends(get_db)):
    return crud.create_session(db, payload.model_dump())


@router.post("/sessions/{session_id}/messages", response_model=MessageResponse, status_code=status.HTTP_201_CREATED)
def create_message(
    session_id: int,
    payload: MessageCreateIn,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
):
    # 세션 확인
    if not crud.get_session(db, session_id):
        raise HTTPException(status_code=404, detail="session not found")

    role = payload.role  # type: ignore[arg-type]

    # 벡터 검증
    if role == "assistant":
        vec = None
    else:
        if payload.vector_memory is None:
            raise HTTPException(status_code=400, detail="vector_memory required for user messages")
        if len(payload.vector_memory) != VECTOR_DIM or not all(isinstance(x, (int, float)) for x in payload.vector_memory):
            raise HTTPException(status_code=400, detail=f"vector_memory must be length {VECTOR_DIM} of numbers")
        vec = [float(x) for x in payload.vector_memory]

    # 저장
    obj = crud.create_message(
        db,
        session_id=session_id,
        role=role,
        content=payload.content,
        vector_memory=vec,
        response_latency_ms=payload.response_latency_ms or 0,
        extra_data=payload.extra_data,  # None 또는 실제 JSON
    )

    # 메트릭 재계산 트리거
    if obj.role == "assistant":
        background_tasks.add_task(_recompute_job)

    return obj

@router.get("/sessions", response_model=list[ChatSessionResponse])
def list_sessions(
    offset: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=100),
    resolved: Optional[bool] = Query(None),
    model_id: Optional[int] = Query(None),
    search: Optional[str] = Query(None, description="search in title"),
    db: Session = Depends(get_db),
):
    return crud.list_sessions(db, offset=offset, limit=limit, resolved=resolved, model_id=model_id, search=search)


@router.get("/sessions/{session_id}", response_model=ChatSessionResponse)
def get_session(session_id: int, db: Session = Depends(get_db)):
    obj = crud.get_session(db, session_id)
    if not obj:
        raise HTTPException(status_code=404, detail="not found")
    return obj


@router.patch("/sessions/{session_id}", response_model=ChatSessionResponse)
def update_session(session_id: int, payload: ChatSessionUpdate, db: Session = Depends(get_db)):
    obj = crud.update_session(db, session_id, payload.model_dump(exclude_unset=True))
    if not obj:
        raise HTTPException(status_code=404, detail="not found")
    return obj


class EndSessionIn(BaseModel):
    resolved: Optional[bool] = None


@router.post("/sessions/{session_id}/end", response_model=ChatSessionResponse)
def end_session(session_id: int, payload: EndSessionIn | None = None, db: Session = Depends(get_db)):
    resolved = payload.resolved if payload else None
    obj = crud.end_session(db, session_id, resolved=resolved)
    if not obj:
        raise HTTPException(status_code=404, detail="not found")
    return obj


@router.delete("/sessions/{session_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_session(session_id: int, db: Session = Depends(get_db)):
    if not crud.delete_session(db, session_id):
        raise HTTPException(status_code=404, detail="not found")
    return None


# -------- Message --------
class MessageCreateIn(MessageCreate):
    vector_memory: Optional[List[float]] = Field(default=None, description="1536-dim vector")

def _recompute_job():
    with SessionLocal() as db:
        recompute_model_metrics(db)

@router.post("/sessions/{session_id}/messages", response_model=MessageResponse, status_code=status.HTTP_201_CREATED)
def create_message(
    session_id: int,
    payload: MessageCreateIn,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
):
    if not crud.get_session(db, session_id):
        raise HTTPException(status_code=404, detail="session not found")

    role = payload.role  # type: ignore[arg-type]

    if role == "assistant":
        vec = None
    else:
        if payload.vector_memory is None:
            raise HTTPException(status_code=400, detail="vector_memory required for user messages")
        if len(payload.vector_memory) != VECTOR_DIM or not all(isinstance(x, (int, float)) for x in payload.vector_memory):
            raise HTTPException(status_code=400, detail=f"vector_memory must be length {VECTOR_DIM} of numbers")
        vec = [float(x) for x in payload.vector_memory]

    obj = crud.create_message(
        db,
        session_id=session_id,
        role=role,
        content=payload.content,
        vector_memory=vec,
        response_latency_ms=payload.response_latency_ms or 0,
        extra_data=payload.extra_data,
    )
    if obj.role == "assistant":
        background_tasks.add_task(_recompute_job)
    return obj


@router.get("/sessions/{session_id}/messages", response_model=list[MessageResponse])
def list_messages(
    session_id: int,
    offset: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=500),
    role: Optional[str] = Query(None, pattern="^(user|assistant)$"),
    db: Session = Depends(get_db),
):
    # 세션 존재 확인
    if not crud.get_session(db, session_id):
        raise HTTPException(status_code=404, detail="session not found")
    return crud.list_messages(db, session_id, offset=offset, limit=limit, role=role)  # type: ignore[arg-type]





@router.get("/messages/{message_id}", response_model=MessageResponse)
def get_message(message_id: int, db: Session = Depends(get_db)):
    obj = crud.get_message(db, message_id)
    if not obj:
        raise HTTPException(status_code=404, detail="not found")
    return obj


@router.delete("/messages/{message_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_message(message_id: int, db: Session = Depends(get_db)):
    if not crud.delete_message(db, message_id):
        raise HTTPException(status_code=404, detail="not found")
    return None


# -------- Feedback --------
@router.post("/feedback", response_model=FeedbackResponse, status_code=status.HTTP_201_CREATED)
def create_feedback(payload: FeedbackCreate, db: Session = Depends(get_db)):
    try:
        return crud.create_feedback(
            db,
            rating=payload.rating,                    # type: ignore[arg-type]
            comment=payload.comment,
            session_id=payload.session_id,
            message_id=payload.message_id,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/sessions/{session_id}/feedback", response_model=FeedbackResponse)
def get_feedback_for_session(session_id: int, db: Session = Depends(get_db)):
    obj = crud.get_feedback_by_session(db, session_id)
    if not obj:
        raise HTTPException(status_code=404, detail="not found")
    return obj


@router.get("/messages/{message_id}/feedback", response_model=FeedbackResponse)
def get_feedback_for_message(message_id: int, db: Session = Depends(get_db)):
    obj = crud.get_feedback_by_message(db, message_id)
    if not obj:
        raise HTTPException(status_code=404, detail="not found")
    return obj


@router.delete("/sessions/{session_id}/feedback", status_code=status.HTTP_204_NO_CONTENT)
def delete_feedback_for_session(session_id: int, db: Session = Depends(get_db)):
    if crud.delete_feedback_by_session(db, session_id) == 0:
        raise HTTPException(status_code=404, detail="not found")
    return None


@router.delete("/messages/{message_id}/feedback", status_code=status.HTTP_204_NO_CONTENT)
def delete_feedback_for_message(message_id: int, db: Session = Depends(get_db)):
    if crud.delete_feedback_by_message(db, message_id) == 0:
        raise HTTPException(status_code=404, detail="not found")
    return None


# -------- Session summary --------
@router.get("/sessions/{session_id}/summary")
def session_summary(session_id: int, db: Session = Depends(get_db)):
    if not crud.get_session(db, session_id):
        raise HTTPException(status_code=404, detail="session not found")
    return crud.session_summary(db, session_id)
