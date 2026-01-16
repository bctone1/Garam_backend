# SCHEMAS/system.py
from __future__ import annotations
from typing import Optional, Literal
from pydantic import BaseModel, Field,ConfigDict
from datetime import datetime

# ----- SystemSetting -----
OperatingHours = Literal["24/7", "business", "extended"]
FileUploadMode = Literal["true", "images", "false"]
SessionDuration = Literal["30", "60", "120", "unlimited"]
MaxMessages = Literal["10", "30", "50", "unlimited"]

class SystemSettingBase(BaseModel):
    welcome_title: Optional[str] = None
    welcome_message: Optional[str] = None
    operating_hours: Optional[OperatingHours] = None
    file_upload_mode: Optional[FileUploadMode] = None
    session_duration: Optional[SessionDuration] = None
    max_messages: Optional[MaxMessages] = None
    emergency_phone: Optional[str] = None
    emergency_email: Optional[str] = None

class SystemSettingCreate(SystemSettingBase):
    # 생성 시 필수로 받길 원하면 Optional 제거하고 필수화하면 됨
    welcome_title: str
    welcome_message: str
    emergency_phone: str
    emergency_email: str

class SystemSettingUpdate(SystemSettingBase):
    pass

class SystemSettingResponse(BaseModel):
    id: int
    welcome_title: str
    welcome_message: str
    operating_hours: OperatingHours
    file_upload_mode: FileUploadMode
    session_duration: SessionDuration
    max_messages: MaxMessages
    emergency_phone: str
    emergency_email: str
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}

# ----- QuickCategory -----

class QuickCategoryBase(BaseModel):
    id: Optional[int] = None
    icon_emoji: Optional[str] = None
    name: Optional[str] = None
    description: Optional[str] = None
    sort_order: Optional[int] = Field(default=None, ge=0)


class QuickCategoryCreate(QuickCategoryBase):
    """
    업서트용으로도 사용 가능하게 변경:
    - id는 선택적 (없으면 새로 생성)
    - name/icon_emoji도 선택 가능 (기존 항목 수정 시 일부 필드만 변경 허용)
    """
    pass


class QuickCategoryUpdate(QuickCategoryBase):
    pass


class QuickCategoryResponse(BaseModel):
    id: int
    icon_emoji: str
    name: str
    description: Optional[str]
    sort_order: int
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


# ----- QuickCategory_Item 서브메뉴 -----

class QuickCategoryItemBase(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None

class QuickCategoryItemCreate(BaseModel):
    quick_category_id: int
    name: str
    description: Optional[str] = None

class QuickCategoryItemUpdate(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None

class QuickCategoryItemResponse(BaseModel):
    id: int
    quick_category_id: int
    name: str
    description: Optional[str] = None

    model_config = {"from_attributes": True}




