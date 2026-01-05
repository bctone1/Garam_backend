# app/endpoints/chat.py
from __future__ import annotations
from typing import Optional, List
from fastapi import APIRouter, Depends, HTTPException, Query, status, BackgroundTasks
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from database.session import get_db, SessionLocal
from crud import chat as crud
from schemas.chat import (
    ChatSessionCreate, ChatSessionUpdate, ChatSessionResponse,
    MessageCreate, MessageResponse,
    FeedbackCreate, FeedbackResponse,
)
from service.metrics import recompute_model_metrics
from core.scheduler import trigger_upsert_today_now
from langchain_service.embedding.get_vector import text_to_vector

router = APIRouter(prefix="/chat", tags=["Chat"])
VECTOR_DIM = 1536

# -------- ChatSession --------
@router.post("/sessions", response_model=ChatSessionResponse, status_code=status.HTTP_201_CREATED)
def create_session(
    payload: ChatSessionCreate,
    db: Session = Depends(get_db),
    background_tasks: BackgroundTasks = None,  # FastAPI가 주입
):
    obj = crud.create_session(db, payload.model_dump())
    # 대시보드: 세션 생성 시 당일 롤업 즉시 갱신(실시간 카드 반영)
    background_tasks.add_task(trigger_upsert_today_now)
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
def end_session(
    session_id: int,
    payload: EndSessionIn | None = None,
    db: Session = Depends(get_db),
    background_tasks: BackgroundTasks = None,  # FastAPI가 주입
):
    resolved = payload.resolved if payload else None
    obj = crud.end_session(db, session_id, resolved=resolved)
    if not obj:
        raise HTTPException(status_code=404, detail="not found")
    # 대시보드: 세션 종료/해결 시 오늘 롤업 갱신 (sessions_resolved 반영)
    background_tasks.add_task(trigger_upsert_today_now)
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
    # 세션 확인
    if not crud.get_session(db, session_id):
        raise HTTPException(status_code=404, detail="session not found")

    role = payload.role  # type: ignore[arg-type]

    if role == "user":
        seq = payload.vector_memory or text_to_vector(payload.content)
        try:
            vec = [float(x) for x in seq]  # numpy/tuple 허용
        except Exception:
            raise HTTPException(status_code=400, detail="vector_memory must be a numeric sequence")
        if len(vec) != VECTOR_DIM:
            raise HTTPException(status_code=400, detail=f"vector_memory must be length {VECTOR_DIM}")
        latency = None
    elif role == "assistant":
        vec = None
        if payload.response_latency_ms is None:
            raise HTTPException(status_code=400, detail="response_latency_ms required for assistant messages")
        latency = int(payload.response_latency_ms)
    else:
        raise HTTPException(status_code=400, detail="invalid role")

    # 'null' 문자열 방지
    extra = None if (isinstance(payload.extra_data, str) and payload.extra_data.lower() == "null") else payload.extra_data

    obj = crud.create_message(
        db,
        session_id=session_id,
        role=role,
        content=payload.content,
        vector_memory=vec,                 # user: list[float], assistant: None
        response_latency_ms=latency,       # user: None, assistant: int
        extra_data=extra,
    )

    if role == "assistant":
        # 모델 메트릭 재계산
        background_tasks.add_task(_recompute_job)
        # 대시보드: 어시스턴트 응답 생성 시 오늘 롤업 즉시 갱신
        background_tasks.add_task(trigger_upsert_today_now)

    return obj

@router.get("/sessions/{session_id}/messages", response_model=list[MessageResponse])
def list_messages(
    session_id: int,
    offset: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=500),
    role: Optional[str] = Query(None, pattern="^(user|assistant)$"),
    db: Session = Depends(get_db),
):
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
            rating=payload.rating,  # type: ignore[arg-type]
            session_id=payload.session_id,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

@router.get("/sessions/{session_id}/feedback", response_model=FeedbackResponse)
def get_feedback_for_session(session_id: int, db: Session = Depends(get_db)):
    obj = crud.get_feedback_by_session(db, session_id)
    if not obj:
        raise HTTPException(status_code=404, detail="not found")
    return obj

@router.delete("/sessions/{session_id}/feedback", status_code=status.HTTP_204_NO_CONTENT)
def delete_feedback_for_session(session_id: int, db: Session = Depends(get_db)):
    if crud.delete_feedback_by_session(db, session_id) == 0:
        raise HTTPException(status_code=404, detail="not found")
    return None


# -------- Session summary --------
@router.get("/sessions/{session_id}/summary")
def session_summary(session_id: int, db: Session = Depends(get_db)):
    if not crud.get_session(db, session_id):
        raise HTTPException(status_code=404, detail="session not found")
    return crud.session_summary(db, session_id)

