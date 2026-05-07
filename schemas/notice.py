from pydantic import BaseModel
from datetime import datetime
from typing import Optional, Literal

NoticeStatus = Literal["scheduled", "active", "expired"]


class NoticeCreate(BaseModel):
    title: str
    content: str
    is_important: bool = False
    author_admin_id: Optional[int] = None
    start_at: Optional[datetime] = None
    end_at: Optional[datetime] = None


class NoticeUpdate(BaseModel):
    title: Optional[str] = None
    content: Optional[str] = None
    is_important: Optional[bool] = None
    author_admin_id: Optional[int] = None
    start_at: Optional[datetime] = None
    end_at: Optional[datetime] = None


class NoticeResponse(BaseModel):
    id: int
    title: str
    content: str
    is_important: bool
    author_admin_id: Optional[int] = None
    start_at: Optional[datetime] = None
    end_at: Optional[datetime] = None
    status: NoticeStatus
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True
