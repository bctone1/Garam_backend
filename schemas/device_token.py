from __future__ import annotations
from datetime import datetime
from typing import Optional, Literal

from pydantic import BaseModel, Field


Platform = Literal["android", "ios"]


class DeviceTokenRegisterIn(BaseModel):
    token: str = Field(..., min_length=10)
    platform: Platform
    app_version: Optional[str] = None
    device_model: Optional[str] = None


class DeviceTokenRegisterOut(BaseModel):
    id: int
    is_active: bool

    class Config:
        from_attributes = True


class DeviceTokenUnregisterIn(BaseModel):
    token: str
