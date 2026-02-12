# 우선 META LLM MSP에서 넘어옴

import json

# from langchain_service.langsmith import logging
from langchain_community.document_loaders import PyPDFLoader
from langchain_core.prompts import PromptTemplate
from core.config import OPENAI_API
from langchain_openai import ChatOpenAI


llm = ChatOpenAI(
    model='gpt-4o', temperature=0,
    # model_name=DEFAULT_CHAT_MODEL,
    # streaming=False,
    openai_api_key=OPENAI_API
)



def pdf_preview_prompt(file_path: str) -> dict:
    loader = PyPDFLoader(file_path)
    documents = loader.load()
    # 앞 페이지 텍스트를 합치기
    full_text = "\n".join([doc.page_content for doc in documents])
    short_text = full_text[:3000]  # 앞 3000자 정도만 LLM에 전달

    prompt = PromptTemplate(
        input_variables=["input_text"],
        template="""
                  "{input_text}"
                  위 내용을 요약해서 아래 JSON 형식으로만 답변하세요:
                  {{
                      "tags": ["...","...","...","..."],
                      "preview": "...",
                  }}
                  """
    )

    chain = prompt | llm
    response = chain.invoke({"input_text": short_text})
    text_output = response.content
    try:
        text_output = text_output.replace("```json", "").replace("```", "").strip()
        text_output = json.loads(text_output)
        return text_output
    except json.JSONDecodeError:
        # JSON이 아닐 경우 fallback 처리
        return {"tags": "", "preview": "text_output"}


def preview_prompt(input: str):
    prompt = PromptTemplate(
        input_variables=["input"],
        template="""
        다음은 사용자가 보낸 요청입니다:
        "{input}"
        위 내용을 요약해서 아래 JSON 형식으로만 답변하세요:
        {{
            "title": "...",
            "preview": "..."
        }}
        """
    )

    chain = prompt | llm
    response = chain.invoke({"input": input})
    # return response
    # text_output = response["text"] # 구버전 코드
    text_output = response.content

    try:
        text_output = text_output.replace("```json", "").replace("```", "").strip()
        text_output = json.loads(text_output)
        return text_output
    except json.JSONDecodeError:
        # JSON이 아닐 경우 fallback 처리
        return {"title": None, "preview": text_output}


