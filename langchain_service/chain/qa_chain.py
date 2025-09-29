from langchain_core.prompts import ChatPromptTemplate
from crud import model as crud_model
from langchain_service.prompt.style import build_system_prompt, llm_params

def make_qa_chain(db, llm_factory, retriever):
    m = crud_model.get_active(db)
    if not m:
        raise RuntimeError("active model not found")

    sys_txt = build_system_prompt(
        style=m.response_style,
        block_inappropriate=m.block_inappropriate,
        restrict_non_tech=m.restrict_non_tech,
        suggest_agent_handoff=m.suggest_agent_handoff,
    )

    prompt = ChatPromptTemplate.from_messages([
        ("system", sys_txt),
        ("system", "다음은 지식베이스 컨텍스트다.\n{context}\n컨텍스트 밖이면 '지식베이스에 없음'이라고 답하라."),
        ("human", "{question}")
    ])

    # 추후 조정 필요
    llm = llm_factory(**llm_params(m.fast_response_mode))
    return prompt | llm  # 필요 시 | RunnablePassthrough 등으로 retriever 조합
