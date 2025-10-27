from pydantic import BaseModel, Field
from datetime import datetime
from typing import Optional

class FAQBase(BaseModel):
    question: str
    answer: str

class FAQCreate(FAQBase):
    quick_category_id: Optional[int] = None
    views: Optional[int] = None
    satisfaction_rate: Optional[float] = Field(default=None, ge=0, le=100)

class FAQUpdate(BaseModel):
    question: Optional[str] = None
    answer: Optional[str] = None
    quick_category_id: Optional[int] = None
    views: Optional[int] = Field(default=None, ge=0)
    satisfaction_rate: Optional[float] = Field(default=None, ge=0, le=100)

class FAQResponse(FAQBase):
    id: int
    quick_category_id: Optional[int] = None
    views: int
    satisfaction_rate: float
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True
