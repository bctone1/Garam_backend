# langchain_service/chain/qa_chain.py
from operator import itemgetter
from langchain_core.runnables import RunnableLambda, RunnableMap
from langchain_core.output_parsers import StrOutputParser
from langchain_core.prompts import ChatPromptTemplate
from crud import model as crud_model
from crud.knowledge import search_chunks_by_vector      # vector search 하는 곳
from langchain_service.prompt.style import build_system_prompt, llm_params


def make_qa_chain(db, get_llm, text_to_vector, *, knowledge_id=None, top_k=5):
    m = crud_model.get_active(db)
    if not m:
        raise RuntimeError("active model not found")

    system_txt = build_system_prompt(
        style=m.response_style,
        block_inappropriate=m.block_inappropriate,
        restrict_non_tech=m.restrict_non_tech,
        suggest_agent_handoff=m.suggest_agent_handoff,
    )

    def _retrieve(question: str) -> str:
        vec = text_to_vector(question)
        chunks = search_chunks_by_vector(
            db, query_vector=vec, knowledge_id=knowledge_id, top_k=top_k
        )
        # 필요 시 길이 제한(LLM 입력 과다 방지)
        context = "\n\n".join(c.chunk_text for c in chunks)
        return context[:5000]  # 간단 컷

    retriever = RunnableLambda(_retrieve)

    prompt = ChatPromptTemplate.from_messages([
        ("system", system_txt),
        ("system", "다음은 지식베이스 컨텍스트다.\n{context}\n"
                   "컨텍스트 밖이면 '해당내용은 찾을 수 없음'이라고만 답하라."),
        ("human", "{question}")
    ])

    llm = get_llm(**llm_params(m.fast_response_mode))

    return (
        RunnableMap({
            "question": itemgetter("question"),
            "context": itemgetter("question") | retriever
        })
        | prompt
        | llm
        | StrOutputParser()
    )
