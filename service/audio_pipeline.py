# SERVICE/audio_pipeline.py
from __future__ import annotations
from typing import Callable, Optional, Dict, Any
from time import perf_counter

from sqlalchemy.orm import Session

from service.stt_service import STTService
from langchain_service.chain.qa_chain import make_qa_chain  # 또는 qa_pipeline로 교체
from crud import chat as crud_chat


def handle_audio_query(
    db: Session,
    audio_path: str,
    *,
    session_id: Optional[int] = None,
    stt: STTService,
    get_llm: Callable[..., object],
    text_to_vector: Callable[[str], list[float]],
    knowledge_id: Optional[int] = None,
    top_k: int = 5,
    max_ctx_chars: int = 5000,
    session_title: Optional[str] = None,
    model_id: Optional[int] = None,
) -> Dict[str, Any]:
    # 1) STT
    user_text = stt.transcribe(audio_path)

    # 2) 세션 확보
    session = crud_chat.create_session(
        db,
        session_id=session_id,
        title=session_title or "Audio Session",
        model_id=model_id,
    )

    # 3) 사용자 메시지 기록(+임베딩)
    user_vec = text_to_vector(user_text)
    user_msg = crud_chat.create_user(
        db,
        session.id,
        content=user_text,
        vector=user_vec,
    )

    # 4) RAG 체인 구성 및 호출
    chain = make_qa_chain(
        db,
        get_llm=get_llm,
        text_to_vector=text_to_vector,
        knowledge_id=knowledge_id,
        top_k=top_k,
        max_ctx_chars=max_ctx_chars,
    )
    t0 = perf_counter()
    answer = chain.invoke(user_text)
    latency_ms = int((perf_counter() - t0) * 1000)

    # 5) 어시스턴트 메시지 기록
    asst_msg = crud_chat.create_message(
        db,
        session_id=session.id,
        role="assistant",
        content=answer,
        vector_memory=None,
        response_latency_ms=latency_ms,
        extra_data=None,
    )

    return {
        "session_id": session.id,
        "user_text": user_text,
        "answer": answer,
        "user_message_id": user_msg.id,
        "assistant_message_id": asst_msg.id,
        "latency_ms": latency_ms,
    }
