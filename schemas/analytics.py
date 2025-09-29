from __future__ import annotations
from datetime import datetime
from typing import List
from pydantic import BaseModel

class InquiryStats(BaseModel):
    total: int
    completed: int
    resolution_rate: float

class DashboardMetricsResponse(BaseModel):
    total_sessions: int
    avg_response_ms: float
    satisfaction_rate: float  # 0~1
    inquiry: InquiryStats
    avg_turns: float
    session_resolved_rate: float  # 0~1

# ts는 time stamp 를 의미/ session 은 그 날 세션의 수/ 그날 평균 응답시간
class DailyPoint(BaseModel):
    ts: datetime
    sessions: int
    avg_response_ms: float

class HourlyPoint(BaseModel):
    ts: datetime
    messages: int

class ModelStat(BaseModel):
    model_id: int
    model_name: str
    provider: str
    sessions: int
    avg_response_ms: float
