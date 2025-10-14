from typing import Optional, Callable
from service.stt_service import STTService
from langchain_service.chain.qa_chain import make_qa_chain

def stt_to_rag(
    db,
    audio_path: str,
    *,
    stt: STTService,
    get_llm: Callable[..., object],
    text_to_vector: Callable[[str], list[float]],
    knowledge_id: Optional[int] = None,
    top_k: int = 5,
    max_ctx_chars: int = 5000,
) -> dict:
    # 1) STT
    text = stt.transcribe(audio_path)
    text = _normalize(text)  # 선택

    # 2) RAG (기존 qa_chain 그대로 사용)
    chain = make_qa_chain(
        db,
        get_llm=get_llm,
        text_to_vector=text_to_vector,
        knowledge_id=knowledge_id,
        top_k=top_k,
        max_ctx_chars=max_ctx_chars,
    )
    answer = chain.invoke(text)
    return {"query": text, "answer": answer}

def _normalize(s: str) -> str:
    return " ".join(s.strip().split())
