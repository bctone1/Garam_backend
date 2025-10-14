# langchain_service/chain/qa_chain.py
from operator import itemgetter
from typing import Optional, Callable
from sqlalchemy.orm import Session

from langchain_core.runnables import RunnableLambda, RunnableMap
from langchain_core.output_parsers import StrOutputParser
from langchain_core.prompts import ChatPromptTemplate

from crud import model as crud_model
from crud.knowledge import search_chunks_by_vector
from langchain_service.prompt.style import build_system_prompt, llm_params
from core import config


def make_qa_chain(
    db: Session,
    get_llm: Callable[..., object],
    text_to_vector: Callable[[str], list[float]],
    *,
    knowledge_id: Optional[int] = None,
    top_k: int = 8,
    max_ctx_chars: int = 12000,
    restrict_to_kb: bool = True,
):
    m = crud_model.get_single(db)
    if not m:
        raise RuntimeError("model not initialized")

    system_txt = build_system_prompt(
        style=m.response_style,
        block_inappropriate=m.block_inappropriate,
        restrict_non_tech=m.restrict_non_tech,
        suggest_agent_handoff=m.suggest_agent_handoff,
    )

    guard_msg = (
        "다음은 지식베이스 컨텍스트다.\n{context}\n"
        "컨텍스트 밖이면 '해당내용은 찾을 수 없음'이라고만 답하라."
        if restrict_to_kb
        else
        "다음은 지식베이스 컨텍스트다.\n{context}\n"
        "컨텍스트를 우선해 답하고, 없으면 모른다고 간단히 답하라."
    )

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

    # llm = get_llm(**llm_params(m.fast_response_mode))

    params = llm_params(m.fast_response_mode)
    provider = getattr(config, "LLM_PROVIDER", "openai")
    model = getattr(config, "LLM_MODEL",
        getattr(config, "DEFAULT_CHAT_MODEL", "gpt-4o-mini"))
    llm = get_llm(provider=provider, model=model,
        temperature = params.get("temperature", 0.7))

    return (
        RunnableMap({
            "question": itemgetter("question"),
            "context": itemgetter("question") | retriever,
        })
        | prompt
        | llm
        | StrOutputParser()
    )