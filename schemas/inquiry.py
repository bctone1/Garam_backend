from pydantic import BaseModel
from datetime import datetime
from typing import Optional, Literal

# -------------------------------
# Inquiry
# -------------------------------
Status = Literal["new", "processing", "on_hold", "completed"]
Satisfaction = Literal["satisfied", "unsatisfied"]

class InquiryBase(BaseModel):
    customer_name: str
    company: Optional[str] = None
    phone: Optional[str] = None
    content: str
    status: Status = "new"
    assignee_admin_id: Optional[int] = None
    customer_satisfaction: Optional[Satisfaction] = None

class InquiryCreate(InquiryBase):
    pass

class InquiryUpdate(BaseModel):
    customer_name: Optional[str] = None
    company: Optional[str] = None
    phone: Optional[str] = None
    content: Optional[str] = None
    status: Optional[Status] = None
    assignee_admin_id: Optional[int] = None
    customer_satisfaction: Optional[Satisfaction] = None
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
Action = Literal[
    "new","assign", "on_hold", "resume", "transfer", "complete", "note", "contact", "delete"
]

class InquiryHistoryBase(BaseModel):
    inquiry_id: int
    action: Action
    # ORM과 맞춤: id 대신 이름 문자열만 저장
    admin_name: Optional[str] = None
    details: Optional[str] = None

class InquiryHistoryCreate(InquiryHistoryBase):
    pass

class InquiryHistoryResponse(InquiryHistoryBase):
    id: int
    created_at: datetime

    class Config:
        from_attributes = True

class AssignIn(BaseModel):
    admin_id: int
    actor_admin_id: Optional[int] = None

class UnassignIn(BaseModel):
    actor_admin_id: Optional[int] = None

class TransferIn(BaseModel):
    to_admin_id: int
    actor_admin_id: Optional[int] = None

class SetStatusIn(BaseModel):
    status: Status
    actor_admin_id: Optional[int] = None
    details: Optional[str] = None

class SatisfactionIn(BaseModel):
    satisfaction: Satisfaction

class HistoryNoteIn(BaseModel):
    admin_id: Optional[int] = None
    details: Optional[str] = None
    action: Optional[str] = None
