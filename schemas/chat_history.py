# schemas/chat_history.py
from __future__ import annotations

from datetime import datetime, date
from typing import Optional, List, Literal, Any, Dict

from pydantic import BaseModel, Field


ChatInsightStatus = Literal["success", "failed", "commit"]
ChannelLiteral = Literal["web", "mobile"]

# 최소 상태(확정)
AnswerStatus = Literal["ok", "error"]
ReviewStatus = Literal["pending", "ingested", "deleted"]


# =========================
# 1) chat_session_insight
# =========================
class ChatSessionInsightBase(BaseModel):
    session_id: int
    started_at: datetime

    channel: Optional[ChannelLiteral] = None
    category: Optional[str] = None
    quick_category_id: Optional[int] = None

    status: ChatInsightStatus = "success"
    first_question: Optional[str] = None
    question_count: int = 0
    failed_reason: Optional[str] = None


class ChatSessionInsightCreate(ChatSessionInsightBase):
    pass


class ChatSessionInsightUpdate(BaseModel):
    started_at: Optional[datetime] = None
    channel: Optional[ChannelLiteral] = None
    category: Optional[str] = None
    quick_category_id: Optional[int] = None

    status: Optional[ChatInsightStatus] = None
    first_question: Optional[str] = None
    question_count: Optional[int] = None
    failed_reason: Optional[str] = None


class ChatSessionInsightResponse(ChatSessionInsightBase):
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


# =========================
# 2) chat_message_insight
# =========================
class ChatMessageInsightBase(BaseModel):
    message_id: int
    session_id: int

    is_question: bool = True
    category: Optional[str] = None
    keywords: Optional[List[str]] = None

    created_at: datetime


class ChatMessageInsightCreate(ChatMessageInsightBase):
    pass


class ChatMessageInsightUpdate(BaseModel):
    is_question: Optional[bool] = None
    category: Optional[str] = None
    keywords: Optional[List[str]] = None
    created_at: Optional[datetime] = None


class ChatMessageInsightResponse(ChatMessageInsightBase):
    class Config:
        from_attributes = True


# =========================
# 3) chat_keyword_daily
# =========================
class ChatKeywordDailyBase(BaseModel):
    dt: date
    keyword: str
    count: int

    channel: Optional[ChannelLiteral] = None
    quick_category_id: Optional[int] = None


class ChatKeywordDailyUpsert(ChatKeywordDailyBase):
    """
    서비스/ETL에서 upsert할 때 쓰는 입력 스키마(외부 API에 노출 안 해도 됨).
    """

    pass


class ChatKeywordDailyResponse(ChatKeywordDailyBase):
    id: int
    updated_at: datetime

    class Config:
        from_attributes = True


# =========================
# Query / Response helpers
# =========================
class ChatHistoryRange(BaseModel):
    """
    공통 기간 필터(대시보드/대화기록 화면용)
    """

    date_from: Optional[date] = None
    date_to: Optional[date] = None  # inclusive/exclusive 처리는 endpoint에서 통일


class ChatSessionInsightListQuery(ChatHistoryRange):
    status: Optional[ChatInsightStatus] = None
    channel: Optional[ChannelLiteral] = None
    category: Optional[str] = None
    quick_category_id: Optional[int] = None

    q: Optional[str] = None
    offset: int = 0
    limit: int = 50


class ChatMessageInsightListQuery(ChatHistoryRange):
    session_id: Optional[int] = None
    channel: Optional[ChannelLiteral] = None
    category: Optional[str] = None

    offset: int = 0
    limit: int = 50


class KeywordTopItem(BaseModel):
    keyword: str
    count: int


class WordCloudQuery(ChatHistoryRange):
    channel: Optional[ChannelLiteral] = None
    quick_category_id: Optional[int] = None
    top_n: int = 100


class WordCloudResponse(BaseModel):
    items: List[KeywordTopItem] = Field(default_factory=list)


# =========================
# 4) knowledge_suggestion (큐)
# =========================
class KnowledgeSuggestionBase(BaseModel):
    session_id: int
    message_id: int

    question_text: str
    assistant_answer: Optional[str] = None

    answer_status: AnswerStatus = "error"
    review_status: ReviewStatus = "pending"

    reason_code: Optional[str] = None
    retrieval_meta: Optional[Dict[str, Any]] = None

    target_knowledge_id: Optional[int] = None
    final_answer: Optional[str] = None


class KnowledgeSuggestionCreate(BaseModel):
    """
    보통 서버가 error 확정 시 자동 생성(upsert).
    (UI 버튼 기반 생성이 필요하면 사용)
    """

    session_id: int
    message_id: int
    question_text: str
    assistant_answer: Optional[str] = None
    reason_code: Optional[str] = None
    retrieval_meta: Optional[Dict[str, Any]] = None


class KnowledgeSuggestionIngestRequest(BaseModel):
    """
    pending -> ingested
    final_answer는 필수.
    target_knowledge_id 미지정이면 suggestion.target_knowledge_id 또는 서버 기본값 사용(엔드포인트에서 처리)
    """

    final_answer: str = Field(..., min_length=1)
    target_knowledge_id: Optional[int] = None


class KnowledgeSuggestionDeleteRequest(BaseModel):
    """
    pending -> deleted
    """

    deleted_reason: Optional[str] = None


class KnowledgeSuggestionResponse(KnowledgeSuggestionBase):
    id: int

    ingested_chunk_id: Optional[int] = None
    ingested_at: Optional[datetime] = None
    deleted_at: Optional[datetime] = None

    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


class KnowledgeSuggestionListQuery(ChatHistoryRange):
    review_status: Optional[ReviewStatus] = None
    answer_status: Optional[AnswerStatus] = None
    session_id: Optional[int] = None
    channel: Optional[ChannelLiteral] = None

    offset: int = 0
    limit: int = 50


class KnowledgeSuggestionCountResponse(BaseModel):
    total: int
    pending: int
    ingested: int
    deleted: int


__all__ = [
    # literals
    "ChatInsightStatus",
    "ChannelLiteral",
    "AnswerStatus",
    "ReviewStatus",
    # session insight
    "ChatSessionInsightCreate",
    "ChatSessionInsightUpdate",
    "ChatSessionInsightResponse",
    # message insight
    "ChatMessageInsightCreate",
    "ChatMessageInsightUpdate",
    "ChatMessageInsightResponse",
    # keyword daily
    "ChatKeywordDailyUpsert",
    "ChatKeywordDailyResponse",
    # queries
    "ChatSessionInsightListQuery",
    "ChatMessageInsightListQuery",
    "WordCloudQuery",
    "WordCloudResponse",
    # knowledge suggestion
    "KnowledgeSuggestionCreate",
    "KnowledgeSuggestionIngestRequest",
    "KnowledgeSuggestionDeleteRequest",
    "KnowledgeSuggestionResponse",
    "KnowledgeSuggestionListQuery",
    "KnowledgeSuggestionCountResponse",
]
