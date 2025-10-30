# schemas/model.py
from __future__ import annotations
from pydantic import BaseModel, Field
from typing import Optional, Literal
from datetime import datetime

ResponseStyle = Literal["professional", "friendly", "concise"]


class ModelUpdate(BaseModel):
    # 일반 설정
    name: Optional[str] = None
    response_style: Optional[ResponseStyle] = None
    block_inappropriate: Optional[bool] = None
    restrict_non_tech: Optional[bool] = None
    suggest_agent_handoff: Optional[bool] = None

    # 지표(원한다면 일반 업데이트에서도 허용)
    accuracy: Optional[float] = Field(default=None, ge=0, le=100)
    avg_response_time_ms: Optional[int] = Field(default=None, ge=0)
    month_conversations: Optional[int] = Field(default=None, ge=0)
    uptime_percent: Optional[float] = Field(default=None, ge=0, le=100)


class ModelResponse(BaseModel):
    id: int
    name: str

    # 지표
    accuracy: float
    avg_response_time_ms: int
    month_conversations: int
    uptime_percent: float

    # 응답 스타일/품질
    response_style: ResponseStyle
    block_inappropriate: bool
    restrict_non_tech: bool
    fast_response_mode: bool
    suggest_agent_handoff: bool

    # 타임스탬프
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}  # Pydantic v2

class MetricsUpdateIn(BaseModel):
    accuracy: Optional[float] = Field(default=None, ge=0, le=100)
    avg_response_time_ms: Optional[int] = Field(default=None, ge=0)
    month_conversations: Optional[int] = Field(default=None, ge=0)
    uptime_percent: Optional[float] = Field(default=None, ge=0, le=100)