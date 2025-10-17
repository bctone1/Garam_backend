from __future__ import annotations
from typing import Optional, Literal
from pydantic import BaseModel, Field, conint
from fastapi import Form

StyleLiteral = Literal['professional','friendly','concise']

class QARequest(BaseModel):
    question: str = Field(..., min_length=1, max_length=4000)
    session_id: Optional[int] = Field(default=None, ge=1)
    knowledge_id: Optional[int] = Field(default=None, ge=1)
    top_k: int = Field(default=5, ge=1, le=50)


class ChatQARequest(BaseModel):
    question: str = Field(..., min_length=1, max_length=4000)
    knowledge_id: Optional[int] = Field(default=None, ge=1)
    top_k: int = Field(default=5, ge=1, le=50)


class QASource(BaseModel):
    chunk_id: Optional[int] = None
    knowledge_id: Optional[int] = None
    page_id: Optional[int] = None
    chunk_index: Optional[int] = None
    text: str = Field(default="")


class QAResponse(BaseModel):
    answer: str
    question: str
    session_id: Optional[int] = None
    sources: list[QASource] = Field(default_factory=list)
    documents: list[QASource] = Field(default_factory=list)

## 응답 설정
class PolicyFlags(BaseModel):
    block_inappropriate: Optional[bool] = None
    restrict_non_tech: Optional[bool] = None
    suggest_agent_handoff: Optional[bool] = None

class ChatQARequest(PolicyFlags):
    question: str
    knowledge_id: Optional[int] = None
    top_k: int = 5
    style: Optional[StyleLiteral] = None

class QARequest(PolicyFlags):
    question: str
    knowledge_id: Optional[int] = None
    top_k: int = 5
    session_id: Optional[int] = None
    style: Optional[StyleLiteral] = None

class STTQAParams(PolicyFlags):
    knowledge_id: Optional[int] = None
    top_k: int = 5
    session_id: Optional[int] = None
    lang: str = "ko-KR"
    style: Optional[StyleLiteral] = None


## STT
class STTResponse(BaseModel):
    text: str

class STTQAParams(BaseModel):
    lang: str = "ko-KR"
    knowledge_id: Optional[int] = None
    top_k: conint(gt=0, le=20) = 5
    session_id: Optional[int] = None

    @classmethod
    def as_form(
        cls,
        lang: str = Form("ko-KR"),
        knowledge_id: Optional[int] = Form(None),
        top_k: int = Form(5),
        session_id: Optional[int] = Form(None),
    ):
        return cls(lang=lang, knowledge_id=knowledge_id, top_k=top_k, session_id=session_id)

