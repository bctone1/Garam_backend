# SCHEMAS/schemas_api_cost.py
from __future__ import annotations
from datetime import date, datetime
from decimal import Decimal
from pydantic import BaseModel, Field, constr, conint, condecimal
from typing import Optional, Literal


ProductStr = constr(strip_whitespace=True, min_length=2, max_length=16)   # llm|embedding|stt|tts|image
ModelStr = constr(strip_whitespace=True, min_length=1, max_length=128)


class ApiCostDailyBase(BaseModel):
    d: date = Field(..., description="KST 기준 날짜")
    product: ProductStr
    model: ModelStr
    llm_tokens: conint(ge=0) = 0
    embedding_tokens: conint(ge=0) = 0
    audio_seconds: conint(ge=0) = 0
    cost_usd: condecimal(max_digits=12, decimal_places=6) = Decimal("0")    ## 합계

    class Config:
        from_attributes = True


class ApiCostDailyCreate(ApiCostDailyBase):
    pass


class ApiCostDailyUpdate(BaseModel):
    llm_tokens: Optional[conint(ge=0)] = None
    embedding_tokens: Optional[conint(ge=0)] = None
    audio_seconds: Optional[conint(ge=0)] = None
    cost_usd: Optional[condecimal(max_digits=12, decimal_places=6)] = None

    class Config:
        from_attributes = True


class ApiCostDailyOut(ApiCostDailyBase):
    updated_at: Optional[datetime] = None

    class Config:
        from_attributes = True

# ===== 요청/응답 스키마 =====
class AddEventRequest(BaseModel):
    ts_utc: datetime = Field(..., description="UTC 기준 호출 시각")
    product: str = Field(..., pattern="^(llm|embedding|stt)$")
    model: str

    # 사용량(사후)
    llm_tokens: conint(ge=0) = 0
    embedding_tokens: conint(ge=0) = 0
    audio_seconds: conint(ge=0) = 0

    # 선택: 외부 정산값을 그대로 씀(>0일 때)
    cost_usd: condecimal(max_digits=12, decimal_places=6) = Decimal("0")


class EnsurePresentRequest(BaseModel):
    date: date
    product: str = Field(..., pattern="^(llm|embedding|stt)$")
    model: str


class TotalsItem(BaseModel):
    date: Optional[date] = None
    product: Optional[str] = None
    model: Optional[str] = None
    llm_tokens: int
    embedding_tokens: int
    audio_seconds: int
    cost_usd: Decimal