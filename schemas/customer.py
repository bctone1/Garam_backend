# schemas/customer.py
from __future__ import annotations

from datetime import datetime
from typing import Optional

from pydantic import BaseModel


class CustomerResponse(BaseModel):
    id: int
    business_number: Optional[str] = None
    business_name: str
    owner_name: Optional[str] = None
    phone: Optional[str] = None
    store_phone: Optional[str] = None
    address: Optional[str] = None
    created_at: datetime

    class Config:
        from_attributes = True


class CustomerCreate(BaseModel):
    business_name: str
    business_number: Optional[str] = None
    owner_name: Optional[str] = None
    phone: Optional[str] = None
    store_phone: Optional[str] = None
    address: Optional[str] = None


class CustomerUpdate(BaseModel):
    business_number: Optional[str] = None
    business_name: Optional[str] = None
    owner_name: Optional[str] = None
    phone: Optional[str] = None
    store_phone: Optional[str] = None
    address: Optional[str] = None


class CustomerListResponse(BaseModel):
    total: int
    items: list[CustomerResponse]


class CsvUploadResponse(BaseModel):
    total: int
    created: int
