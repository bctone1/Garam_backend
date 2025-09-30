# Pydantic 스키마 (요청/응답)

from pydantic import BaseModel
from datetime import datetime
from typing import Optional


# -------------------------------
# Inquiry
# -------------------------------
class InquiryBase(BaseModel):
    customer_name: str
    company: Optional[str] = None
    phone: Optional[str] = None
    content: str
    status: str  # 'new' | 'processing' | 'on_hold' | 'completed'
    assignee_admin_id: Optional[int] = None
    customer_satisfaction: Optional[str] = None  # 'satisfied' | 'unsatisfied'


class InquiryCreate(InquiryBase):
    pass


class InquiryUpdate(BaseModel):
    customer_name: Optional[str] = None
    company: Optional[str] = None
    phone: Optional[str] = None
    content: Optional[str] = None
    status: Optional[str] = None
    assignee_admin_id: Optional[int] = None
    customer_satisfaction: Optional[str] = None
    assigned_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None


class InquiryResponse(InquiryBase):
    id: int
    created_at: datetime
    assigned_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None

    class Config:
        from_attributes = True


# -------------------------------
# InquiryHistory
# -------------------------------
class InquiryHistoryBase(BaseModel):
    inquiry_id: int
    action: str  # 'assign' | 'on_hold' | 'resume' | 'transfer' | 'complete' | 'note' | 'contact' | 'delete'
    admin_id: Optional[int] = None
    to_admin_id: Optional[int] = None
    details: Optional[str] = None


class InquiryHistoryCreate(InquiryHistoryBase):
    pass


class InquiryHistoryResponse(InquiryHistoryBase):
    id: int
    created_at: datetime

    class Config:
        from_attributes = True
