# 임시 코드
## 대화기록 여부 검토
### session안에서 리트리버 역할을 할 수 도 있는데 로그인 방식이 아니라 세션별로 기억할 필요가 없다는 점이 우려되나
#### 관리자가 어떠한 질문이 들어왔는지 확인해야 하므로 모두 사용자의 질문은 DB화 하여 저장해 두어야 한다.


from typing import Tuple
from sqlalchemy.orm import Session
from langchain.chains import RetrievalQA
from langchain_core.prompts import PromptTemplate
from langchain_core.output_parsers import StrOutputParser
from langchain_service.chain.qa_chain import make_qa_chain


from langchain_service.embedding.get_vector import text_to_vector
from crud import chat as crud_chat
from crud import knowledge as crud_knowledge
from langchain_service.llm.setup import get_llm


class QAPipeline:
    def __init__(self, provider="openai", model="gpt-4o", api_key=None, top_k=3):
        self.llm = get_llm(provider, model, api_key=api_key)
        self.top_k = top_k

        self.prompt = PromptTemplate(
            input_variables=["history", "context", "input"],
            template=(
                "아래 문맥과 대화 히스토리를 참고하여 질문에 답하세요.\n"
                "문맥:\n{context}\n\n"
                "대화 히스토리:\n{history}\n\n"
                "질문: {input}\n\n"
                "AI:"
            ),
        )

    def answer(self, db: Session, session_id: int, question: str) -> str:
        # 1. 질문 벡터화
        q_vector = text_to_vector(question)

        # 2. 지식베이스 검색
        docs = crud_knowledge.search_chunks(db, q_vector, top_k=self.top_k)
        context = "\n".join([d.chunk_text for d in docs])

        # 3. 대화 기록 검색
        history_msgs = crud_chat.get_relevant_messages(db, session_id, q_vector, top_n=5)
        history = "\n".join([f"{m['role'].capitalize()}: {m['content']}" for m in history_msgs])

        # 4. 체인 실행
        chain = make_qa_chain(db, get_llm, text_to_vector)
        # chain = self.prompt | self.llm | StrOutputParser()
        answer = chain.invoke({"history": history, "context": context, "input": question})

        # 5. 대화 로그 저장
        crud_chat.save_message(db, session_id, "user", question, q_vector)
        crud_chat.save_message(db, session_id, "assistant", answer, None)

        return answer
