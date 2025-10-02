from __future__ import annotations

from typing import Iterable, Optional

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from crud import chat as crud_chat
from crud import knowledge as crud_knowledge
from database.session import get_db
from langchain_service.chain.qa_chain import make_qa_chain
from langchain_service.embedding.get_vector import text_to_vector
from langchain_service.llm.setup import get_llm
from schemas.llm import ChatQARequest, QARequest, QAResponse, QASource


router = APIRouter(tags=["LLM"])


def _ensure_session(db: Session, session_id: int) -> None:
    if not crud_chat.get_session(db, session_id):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="session not found")


def _to_vector(question: str) -> list[float]:
    vector = text_to_vector(question)
    if vector is None:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="임베딩 생성에 실패했습니다.")
    if hasattr(vector, "tolist"):
        vector_list = vector.tolist()
    else:
        vector_list = list(vector)
    if not vector_list:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="임베딩 생성에 실패했습니다.")
    return [float(v) for v in vector_list]


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
) -> QAResponse:
    vector = _to_vector(question)
    if session_id is not None:
        _update_last_user_vector(db, session_id, vector)

    try:
        chain = make_qa_chain(db, get_llm, text_to_vector, knowledge_id=knowledge_id, top_k=top_k)
    except RuntimeError as exc:  # active model 이 없을 때 등
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc)) from exc

    try:
        answer = chain.invoke({"question": question})
    except Exception as exc:  # pragma: no cover - 외부 LLM 예외 래핑
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail="LLM 호출에 실패했습니다.") from exc

    sources = _build_sources(db, vector, knowledge_id, top_k)
    return QAResponse(
        answer=str(answer),
        question=question,
        session_id=session_id,
        sources=sources,
        documents=sources,
    )


@router.post("/chat/sessions/{session_id}/qa", response_model=QAResponse)
def ask_in_session(session_id: int, payload: ChatQARequest, db: Session = Depends(get_db)) -> QAResponse:
    _ensure_session(db, session_id)
    return _run_qa(
        db,
        question=payload.question,
        knowledge_id=payload.knowledge_id,
        top_k=payload.top_k,
        session_id=session_id,
    )


@router.post("/qa", response_model=QAResponse)
def ask_global(payload: QARequest, db: Session = Depends(get_db)) -> QAResponse:
    session_id = payload.session_id
    if session_id is not None:
        _ensure_session(db, session_id)
    return _run_qa(
        db,
        question=payload.question,
        knowledge_id=payload.knowledge_id,
        top_k=payload.top_k,
        session_id=session_id,
    )


@router.post("/qa/query", response_model=QAResponse)
def ask_global_alias(payload: QARequest, db: Session = Depends(get_db)) -> QAResponse:
    return ask_global(payload, db)
