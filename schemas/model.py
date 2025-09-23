# Pydantic 스키마 (요청/응답)

from pydantic import BaseModel, Field
from datetime import datetime
from typing import Optional, Literal, List, Union

ResponseStyle = Literal["professional", "friendly", "concise"]
FeatureItem = Union[dict, str, int, float, bool]

class ModelBase(BaseModel):
    name: str
    provider_name: str
    description: str
    features: List[FeatureItem] = Field(default_factory=list)

    is_active: bool = False
    status_text: str

    accuracy: float = Field(0, ge=0, le=100)
    avg_response_time_ms: int = Field(0, ge=0)
    month_conversations: int = Field(0, ge=0)
    uptime_percent: float = Field(0, ge=0, le=100)

    response_style: ResponseStyle = "professional"
    block_inappropriate: bool = False
    restrict_non_tech: bool = False
    fast_response_mode: bool = False
    suggest_agent_handoff: bool = False


class ModelCreate(ModelBase):
    pass


class ModelUpdate(BaseModel):
    name: Optional[str] = None
    provider_name: Optional[str] = None
    description: Optional[str] = None
    features: Optional[List[FeatureItem]] = None

    is_active: Optional[bool] = None
    status_text: Optional[str] = None

    accuracy: Optional[float] = Field(default=None, ge=0, le=100)
    avg_response_time_ms: Optional[int] = Field(default=None, ge=0)
    month_conversations: Optional[int] = Field(default=None, ge=0)
    uptime_percent: Optional[float] = Field(default=None, ge=0, le=100)

    response_style: Optional[ResponseStyle] = None
    block_inappropriate: Optional[bool] = None
    restrict_non_tech: Optional[bool] = None
    fast_response_mode: Optional[bool] = None
    suggest_agent_handoff: Optional[bool] = None


class ModelResponse(ModelBase):
    id: int
    created_at: datetime
    updated_at: datetime

    class Config:
        orm_mode = True
