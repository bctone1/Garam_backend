# app/endpoints/llm.py
from __future__ import annotations

from typing import Any, Dict, List, Literal, Optional, Union

from fastapi import APIRouter, Depends, File, Form, UploadFile
from sqlalchemy.orm import Session

from database.session import get_db
from schemas.llm import ChatQARequest, QAResponse, STTResponse
from service.llm_service import (
    ask_in_session_service,
    clova_stt_service,
    list_session_messages_service,
)

router = APIRouter(prefix="/llm", tags=["LLM"])


@router.post("/chat/sessions/{session_id}/qa", response_model=QAResponse, summary="LLM 입력창")
def ask_in_session(session_id: int, payload: ChatQARequest, db: Session = Depends(get_db)) -> QAResponse:
    return ask_in_session_service(db, session_id=session_id, payload=payload)


@router.post("/clova_stt", response_model=Union[STTResponse, QAResponse])
async def clova_stt(
    file: UploadFile = File(...),
    lang: str = Form("ko-KR"),
    db: Session = Depends(get_db),
    # QA 모드용 선택 파라미터
    knowledge_id: Optional[int] = Form(None),
    top_k: int = Form(5),
    session_id: Optional[int] = Form(None),
    style: Optional[str] = Form(None),
    block_inappropriate: Optional[bool] = Form(None),
    restrict_non_tech: Optional[bool] = Form(None),
    suggest_agent_handoff: Optional[bool] = Form(None),
    few_shot_profile: str = Form("support_md"),
):
    raw = await file.read()
    content_type = file.content_type or ""
    return clova_stt_service(
        db,
        raw=raw,
        content_type=content_type,
        lang=lang,
        knowledge_id=knowledge_id,
        top_k=top_k,
        session_id=session_id,
        style=style,
        block_inappropriate=block_inappropriate,
        restrict_non_tech=restrict_non_tech,
        suggest_agent_handoff=suggest_agent_handoff,
        few_shot_profile=few_shot_profile,
    )


@router.get(
    "/chat/sessions/{session_id}/messages",
    summary="세션 메시지 조회(user+assistant)",
    response_model=List[Dict[str, Any]],
)
def get_session_messages(
    session_id: int,
    offset: int = 0,
    limit: int = 200,
    role: Optional[Literal["user", "assistant"]] = None,
    db: Session = Depends(get_db),
):
    return list_session_messages_service(db, session_id=session_id, offset=offset, limit=limit, role=role)
