from __future__ import annotations

from typing import Optional

from pydantic import BaseModel, Field


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
