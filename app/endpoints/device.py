# app/endpoints/device.py
"""푸시 알림용 디바이스 토큰 등록/해제."""
from __future__ import annotations
from fastapi import APIRouter, Depends, status
from sqlalchemy.orm import Session

from database.session import get_db
from crud import device_token as crud
from schemas.device_token import (
    DeviceTokenRegisterIn,
    DeviceTokenRegisterOut,
    DeviceTokenUnregisterIn,
)

router = APIRouter(prefix="/devices", tags=["Device"])


@router.post("/register", response_model=DeviceTokenRegisterOut)
def register_device(payload: DeviceTokenRegisterIn, db: Session = Depends(get_db)):
    obj = crud.upsert(
        db,
        token=payload.token,
        platform=payload.platform,
        app_version=payload.app_version,
        device_model=payload.device_model,
    )
    return DeviceTokenRegisterOut(id=obj.id, is_active=obj.is_active)


@router.post("/unregister", status_code=status.HTTP_204_NO_CONTENT)
def unregister_device(payload: DeviceTokenUnregisterIn, db: Session = Depends(get_db)):
    crud.deactivate(db, payload.token)
    return None
