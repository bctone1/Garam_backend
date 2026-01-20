# schemas/llm.py
from __future__ import annotations

from typing import Optional, Literal, List, Dict, Any

from pydantic import BaseModel, Field, ConfigDict, model_validator


# =========================
# literals
# =========================
StyleLiteral = Literal["professional", "friendly", "concise"]
ChannelLiteral = Literal["web", "mobile"]


# =========================
# 공통 플래그
# =========================
class PolicyFlags(BaseModel):
    """
    LLM/QA 정책 플래그(옵션).
    엔드포인트/서비스에서 getattr로 뽑아 쓰기 쉬운 형태로 유지.
    """
    model_config = ConfigDict(extra="ignore")

    block_inappropriate: Optional[bool] = None
    restrict_non_tech: Optional[bool] = None
    suggest_agent_handoff: Optional[bool] = None


# =========================
# QA 요청/응답
# =========================
class ChatQARequest(PolicyFlags):
    """
    /chat/sessions/{session_id}/qa 전용 요청 바디
    (session_id는 path param)
    """
    model_config = ConfigDict(extra="ignore")

    role: Literal["user"] = "user"  # 세션 QA는 user만 허용
    question: str = Field(..., min_length=1, max_length=4000)

    knowledge_id: Optional[int] = Field(default=None, ge=1)
    top_k: int = Field(default=5, ge=1, le=50)

    style: Optional[StyleLiteral] = None
    few_shot_profile: Optional[str] = Field(default=None, min_length=1, max_length=200)

    # 운영 규칙: web | mobile 고정 코드
    channel: Optional[ChannelLiteral] = Field(default=None)


class QASource(BaseModel):
    """
    검색 근거(청크) 표준 표현.
    runner/_run_qa에서 내려주는 형태와 호환되게 optional을 넉넉히 둠.
    """
    model_config = ConfigDict(from_attributes=True, extra="ignore")

    chunk_id: Optional[int] = None
    knowledge_id: Optional[int] = None
    page_id: Optional[int] = None
    chunk_index: Optional[int] = None

    text: str = Field(default="")


class QACitation(BaseModel):
    knowledge_id: Optional[int] = None
    chunk_id: Optional[int] = None
    page_id: Optional[int] = None
    score: Optional[float] = None


class QAResponse(BaseModel):
    """
    QA 응답 표준.
    - sources: 표준 필드
    - documents: 과거 호환용(=sources)
    """
    model_config = ConfigDict(from_attributes=True, extra="ignore")

    question: str
    answer: str
    session_id: Optional[int] = None

    status: Literal["ok", "no_knowledge", "need_clarification"] = "ok"
    reason_code: Optional[str] = None
    citations: List[QACitation] = Field(default_factory=list)

    sources: List[QASource] = Field(default_factory=list)
    documents: List[QASource] = Field(default_factory=list)
    retrieval_meta: Optional[Dict[str, Any]] = None

    @model_validator(mode="after")
    def _sync_sources_documents(self) -> "QAResponse":
        # 둘 중 하나만 채워져도 동일하게 맞춰줌(레거시 호환)
        if self.sources and not self.documents:
            self.documents = list(self.sources)
        elif self.documents and not self.sources:
            self.sources = list(self.documents)
        return self


# =========================
# STT
# =========================
class STTResponse(BaseModel):
    model_config = ConfigDict(extra="ignore")
    text: str = Field(..., min_length=1)
