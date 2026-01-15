from __future__ import annotations

from datetime import datetime
from typing import Optional, Literal, List

from pydantic import BaseModel, Field

# -------------------------------
# Inquiry
# -------------------------------
Status = Literal["new", "processing", "on_hold", "completed"]
Satisfaction = Literal["satisfied", "unsatisfied"]

InquiryType = Literal["paper_request", "sales_report", "kiosk_menu_update", "other"]
StorageType = Literal["local", "s3"]


# -------------------------------
# InquiryAttachment
# -------------------------------
class InquiryAttachmentBase(BaseModel):
    storage_type: StorageType = "local"
    storage_key: str
    original_name: Optional[str] = None
    content_type: Optional[str] = None
    size_bytes: Optional[int] = None


class InquiryAttachmentCreate(InquiryAttachmentBase):
    pass


class InquiryAttachmentResponse(InquiryAttachmentBase):
    id: int
    inquiry_id: int
    created_at: datetime

    class Config:
        from_attributes = True


# -------------------------------
# Inquiry
# -------------------------------
class InquiryBase(BaseModel):
    business_name: str
    business_number: Optional[str] = None

    phone: Optional[str] = None
    content: str
    inquiry_type: InquiryType = "other"
    status: Status = "new"

    assignee_admin_id: Optional[int] = None

    assigned_by_admin_id: Optional[int] = None
    delegated_from_admin_id: Optional[int] = None
    completed_by_admin_id: Optional[int] = None

    customer_satisfaction: Optional[Satisfaction] = None


class InquiryCreate(InquiryBase):
    attachments: Optional[List[InquiryAttachmentCreate]] = None


class InquiryUpdate(BaseModel):
    business_name: Optional[str] = None
    business_number: Optional[str] = None

    phone: Optional[str] = None
    content: Optional[str] = None
    inquiry_type: Optional[InquiryType] = None
    status: Optional[Status] = None

    assignee_admin_id: Optional[int] = None

    assigned_by_admin_id: Optional[int] = None
    delegated_from_admin_id: Optional[int] = None
    completed_by_admin_id: Optional[int] = None

    customer_satisfaction: Optional[Satisfaction] = None

    assigned_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None


class InquiryResponse(InquiryBase):
    id: int
    created_at: datetime
    assigned_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None

    attachments: Optional[List[InquiryAttachmentResponse]] = None

    class Config:
        from_attributes = True


# -------------------------------
# InquiryHistory
# -------------------------------
Action = Literal[
    "new",
    "assign",
    "on_hold",
    "resume",
    "transfer",
    "complete",
    "note",
    "contact",
    "delete",
]


class InquiryHistoryBase(BaseModel):
    inquiry_id: int
    action: Action
    admin_name: Optional[str] = None
    details: Optional[str] = None


class InquiryHistoryCreate(InquiryHistoryBase):
    pass


class InquiryHistoryResponse(InquiryHistoryBase):
    id: int
    created_at: datetime

    class Config:
        from_attributes = True


# -------------------------------
# Workflow inputs
# -------------------------------
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
