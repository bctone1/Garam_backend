# Pydantic 스키마 (요청/응답)

from pydantic import BaseModel, Field
from datetime import datetime
from typing import Optional


class FAQBase(BaseModel):
    question: str
    answer: str


class FAQCreate(FAQBase):
    # DB 기본값 활용. 필요 시 입력 허용.
    views: Optional[int] = None
    satisfaction_rate: Optional[float] = Field(default=None, ge=0, le=100)


class FAQUpdate(BaseModel):
    question: Optional[str] = None
    answer: Optional[str] = None
    views: Optional[int] = Field(default=None, ge=0)
    satisfaction_rate: Optional[float] = Field(default=None, ge=0, le=100)


class FAQResponse(FAQBase):
    id: int
    views: int
    satisfaction_rate: float
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True
