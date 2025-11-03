# langchain_service/chain/qa_chain.py
from operator import itemgetter
from typing import Optional, Callable, List, Any
from sqlalchemy.orm import Session

from langchain_core.runnables import RunnableLambda, RunnableMap
from langchain_core.output_parsers import StrOutputParser
from langchain_core.prompts import ChatPromptTemplate

from crud import model as crud_model
from crud.knowledge import search_chunks_by_vector
from langchain_service.prompt.style import build_system_prompt, llm_params, STYLE_MAP
from core import config


def make_qa_chain(
    db: Session,
    get_llm: Callable[..., object],
    text_to_vector: Callable[[str], list[float]],
    *,
    knowledge_id: Optional[int] = None,
    top_k: int = 8,
    policy_flags: dict | None = None,
    style: str = "friendly",
    max_ctx_chars: int = 12000,
    restrict_to_kb: bool = True,
    streaming: bool = False,
    callbacks: Optional[List[Any]] = None,  # 비용 집계용 콜백
):
    m = crud_model.get_single(db)
    if not m:
        raise RuntimeError("model not initialized")

    style = style if style in STYLE_MAP else "friendly"
    system_txt = build_system_prompt(style=style, **(policy_flags or {}))

    def _retrieve(question: str) -> str:
        vec = text_to_vector(question)
        chunks = search_chunks_by_vector(
            db, query_vector=vec, knowledge_id=knowledge_id, top_k=top_k
        )
        return "\n\n".join(c.chunk_text for c in chunks)[:max_ctx_chars]

    retriever = RunnableLambda(_retrieve)

    prompt = ChatPromptTemplate.from_messages([
        ("system", system_txt + "\n"
         "규칙: 제공된 컨텍스트를 우선하여 답하고, 정말 관련이 없을 때만 "
         "짧게 '해당내용은 찾을 수 없음'이라고 답하라."),
        ("human",
         "다음 컨텍스트만 근거로 답하세요.\n"
         "[컨텍스트 시작]\n{context}\n[컨텍스트 끝]\n\n"
         "질문: {question}")
    ])

    params = llm_params(m.fast_response_mode)
    provider = getattr(config, "LLM_PROVIDER", "openai")
    model = getattr(config, "LLM_MODEL",
                    getattr(config, "DEFAULT_CHAT_MODEL", "gpt-4o-mini"))

    llm = get_llm(
        provider=provider,
        model=model,
        temperature=params.get("temperature", 0.7),
        streaming=streaming,
    )

    # 콜백을 LLM 노드에 직접 주입 (+run_name)
    if callbacks:
        try:
            llm = llm.with_config(callbacks=callbacks, run_name="qa_llm")
        except Exception:
            pass

    return (
        RunnableMap({
            "question": itemgetter("question"),
            "context": itemgetter("question") | retriever,
        })
        | prompt
        | llm
        | StrOutputParser()
    )
