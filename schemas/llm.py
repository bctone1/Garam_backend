from __future__ import annotations

from typing import Optional, Literal
from pydantic import BaseModel, Field, conint, ConfigDict
from fastapi import Form

StyleLiteral = Literal["professional", "friendly", "concise"]
RoleLiteral = Literal["user", "assistant"]


# =========================
# 공통 플래그
# =========================
class PolicyFlags(BaseModel):
    model_config = ConfigDict(extra="ignore")
    block_inappropriate: Optional[bool] = None
    restrict_non_tech: Optional[bool] = None
    suggest_agent_handoff: Optional[bool] = None


# =========================
# QA 요청/응답
# =========================
class ChatQARequest(PolicyFlags):
    # 세션 QA: session_id는 path로 받으니까 여기서는 제외
    role: RoleLiteral = "user"
    question: str = Field(..., min_length=1, max_length=4000)
    knowledge_id: Optional[int] = Field(default=None, ge=1)
    top_k: int = Field(default=5, ge=1, le=50)
    style: Optional[StyleLiteral] = None
    few_shot_profile: Optional[str] = None


class QARequest(PolicyFlags):
    # 글로벌 QA
    role: RoleLiteral = "user"
    question: str = Field(..., min_length=1, max_length=4000)
    session_id: Optional[int] = Field(default=None, ge=1)
    knowledge_id: Optional[int] = Field(default=None, ge=1)
    top_k: int = Field(default=5, ge=1, le=50)
    style: Optional[StyleLiteral] = None


class QASource(BaseModel):
    model_config = ConfigDict(extra="ignore")
    chunk_id: Optional[int] = None
    knowledge_id: Optional[int] = None
    page_id: Optional[int] = None
    chunk_index: Optional[int] = None
    text: str = Field(default="")


class QAResponse(BaseModel):
    model_config = ConfigDict(extra="ignore")
    answer: str
    question: str
    session_id: Optional[int] = None
    sources: list[QASource] = Field(default_factory=list)
    documents: list[QASource] = Field(default_factory=list)


# =========================
# STT
# =========================
class STTResponse(BaseModel):
    text: str


class STTQAParams(PolicyFlags):
    model_config = ConfigDict(extra="ignore")

    lang: str = "ko-KR"
    knowledge_id: Optional[int] = Field(default=None, ge=1)
    top_k: conint(gt=0, le=20) = 5
    session_id: Optional[int] = Field(default=None, ge=1)
    style: Optional[StyleLiteral] = None

    @classmethod
    def as_form(
        cls,
        lang: str = Form("ko-KR"),
        knowledge_id: Optional[int] = Form(None),
        top_k: int = Form(5),
        session_id: Optional[int] = Form(None),
        style: Optional[str] = Form(None),
        block_inappropriate: Optional[bool] = Form(None),
        restrict_non_tech: Optional[bool] = Form(None),
        suggest_agent_handoff: Optional[bool] = Form(None),
    ):
        return cls(
            lang=lang,
            knowledge_id=knowledge_id,
            top_k=top_k,
            session_id=session_id,
            style=style,
            block_inappropriate=block_inappropriate,
            restrict_non_tech=restrict_non_tech,
            suggest_agent_handoff=suggest_agent_handoff,
        )
