# Pydantic 스키마 (요청/응답)

from pydantic import BaseModel, Field, EmailStr
from datetime import datetime
from typing import Optional, Literal

# ========== SystemSetting ==========

OperatingHours = Literal["24/7", "business", "extended"]
FileUploadMode = Literal["true", "images", "false"]
SessionDuration = Literal["30", "60", "120", "unlimited"]
MaxMessages = Literal["10", "30", "50", "unlimited"]


class SystemSettingBase(BaseModel):
    welcome_title: str
    welcome_message: str
    operating_hours: OperatingHours = "business"
    file_upload_mode: FileUploadMode = "true"
    session_duration: SessionDuration = "60"
    max_messages: MaxMessages = "30"
    emergency_phone: str
    emergency_email: EmailStr


class SystemSettingCreate(SystemSettingBase):
    # DB 기본값을 쓰려면 필요 필드만 전달하고 나머지는 생략 가능
    pass


class SystemSettingUpdate(BaseModel):
    welcome_title: Optional[str] = None
    welcome_message: Optional[str] = None
    operating_hours: Optional[OperatingHours] = None
    file_upload_mode: Optional[FileUploadMode] = None
    session_duration: Optional[SessionDuration] = None
    max_messages: Optional[MaxMessages] = None
    emergency_phone: Optional[str] = None
    emergency_email: Optional[EmailStr] = None


class SystemSettingResponse(SystemSettingBase):
    id: int
    created_at: datetime
    updated_at: datetime

    class Config:
        orm_mode = True


# ========== QuickCategory ==========

class QuickCategoryBase(BaseModel):
    setting_id: int
    icon_emoji: str
    name: str
    description: Optional[str] = None
    sort_order: int = Field(0, ge=0)


class QuickCategoryCreate(QuickCategoryBase):
    pass


class QuickCategoryUpdate(BaseModel):
    icon_emoji: Optional[str] = None
    name: Optional[str] = None
    description: Optional[str] = None
    sort_order: Optional[int] = Field(default=None, ge=0)


class QuickCategoryResponse(QuickCategoryBase):
    id: int
    created_at: datetime
    updated_at: datetime

    class Config:
        orm_mode = True
