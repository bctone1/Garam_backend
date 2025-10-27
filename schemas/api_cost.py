# SCHEMAS/schemas_api_cost.py
from __future__ import annotations
from datetime import date, datetime
from decimal import Decimal
from typing import Optional
from pydantic import BaseModel, Field, constr, conint, condecimal

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
        orm_mode = True


class ApiCostDailyCreate(ApiCostDailyBase):
    pass


class ApiCostDailyUpdate(BaseModel):
    llm_tokens: Optional[conint(ge=0)] = None
    embedding_tokens: Optional[conint(ge=0)] = None
    audio_seconds: Optional[conint(ge=0)] = None
    cost_usd: Optional[condecimal(max_digits=12, decimal_places=6)] = None

    class Config:
        orm_mode = True


class ApiCostDailyOut(ApiCostDailyBase):
    updated_at: Optional[datetime] = None

    class Config:
        orm_mode = True
