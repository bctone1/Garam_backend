from __future__ import annotations
from datetime import date, datetime
from typing import Dict
from pydantic import BaseModel, ConfigDict

class DailyDashboardBase(BaseModel):
    d: date
    weekday: int
    sessions_total: int
    sessions_with_assistant: int
    sessions_resolved: int
    messages_total: int
    avg_response_ms: float
    p50_response_ms: float
    p90_response_ms: float
    avg_turns: float
    inquiries_created: int
    feedback_helpful: int
    feedback_not_helpful: int
    sessions_by_hour: Dict[str, int]
    model_config = ConfigDict(from_attributes=True)

class DailyDashboardResponse(DailyDashboardBase):
    updated_at: datetime

class WindowAveragesResponse(BaseModel):
    avg_sessions: float
    avg_messages: float
    avg_response_ms: float
    avg_turns: float
    resolve_rate_excluding_noresp: float  # resolved / sessions_with_assistant
    csat_rate: float                      # helpful / (helpful+not_helpful)

class UpsertPayload(BaseModel):
    start: date
    end: date
