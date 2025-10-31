# Pydantic 스키마 (요청/응답)
from pydantic import BaseModel
from datetime import datetime
from typing import Optional, List, Any


# -------------------------------
# ChatSession
# -------------------------------
class ChatSessionBase(BaseModel):
    title: str
    preview: Optional[str] = None
    resolved: bool = False
    model_id: Optional[int] = None


class ChatSessionCreate(ChatSessionBase):
    pass


class ChatSessionUpdate(BaseModel):
    title: Optional[str] = None
    preview: Optional[str] = None
    resolved: Optional[bool] = None
    model_id: Optional[int] = None
    ended_at: Optional[datetime] = None


class ChatSessionResponse(ChatSessionBase):
    id: int
    created_at: datetime
    ended_at: Optional[datetime] = None

    class Config:
        from_attributes = True


# -------------------------------
# Message
# -------------------------------
class MessageBase(BaseModel):
    session_id: int
    role: str       # 'user' | 'assistant'
    content: str
    response_latency_ms: Optional[int] = None
    extra_data: Optional[Any] = None


class MessageCreate(MessageBase):
    # vector_memory는 내부적으로 DB 저장용이라 일반 입력엔 생략 가능
    pass


class MessageUpdate(BaseModel):
    content: Optional[str] = None
    response_latency_ms: Optional[int] = None
    extra_data: Optional[Any] = None


class MessageResponse(MessageBase):
    id: int
    created_at: datetime

    class Config:
        from_attributes = True


# -------------------------------
# Feedback
# -------------------------------
class FeedbackBase(BaseModel):
    rating: str       # 'helpful' | 'not_helpful' | null
    session_id: Optional[int] = None


class FeedbackCreate(FeedbackBase):
    pass


class FeedbackUpdate(BaseModel):
    rating: Optional[str] = None
    comment: Optional[str] = None


class FeedbackResponse(FeedbackBase):
    id: int
    created_at: datetime

    class Config:
        from_attributes = True
