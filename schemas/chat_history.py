# schemas/chat_history.py
from __future__ import annotations

from datetime import datetime, date
from typing import Optional, List, Literal

from pydantic import BaseModel, Field


ChatInsightStatus = Literal["success", "failed"]
ChannelLiteral = Literal["web", "mobile"]


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
    date_to: Optional[date] = None  # inclusive로 쓸지 exclusive로 쓸지는 endpoint에서 통일


class ChatSessionInsightListQuery(ChatHistoryRange):
    status: Optional[ChatInsightStatus] = None
    channel: Optional[ChannelLiteral] = None
    category: Optional[str] = None
    quick_category_id: Optional[int] = None

    q: Optional[str] = None  # first_question/preview 등 부분검색용(선택)
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


__all__ = [
    "ChatInsightStatus",
    "ChatSessionInsightCreate",
    "ChatSessionInsightUpdate",
    "ChatSessionInsightResponse",
    "ChatMessageInsightCreate",
    "ChatMessageInsightUpdate",
    "ChatMessageInsightResponse",
    "ChatKeywordDailyUpsert",
    "ChatKeywordDailyResponse",
    "ChatSessionInsightListQuery",
    "ChatMessageInsightListQuery",
    "WordCloudQuery",
    "WordCloudResponse",
]
