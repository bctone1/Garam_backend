# crud/device_token.py
from __future__ import annotations
from datetime import datetime, timezone
from typing import List, Optional, Sequence
from sqlalchemy import select, update
from sqlalchemy.orm import Session

from models.device_token import DeviceToken


def upsert(
    db: Session,
    *,
    token: str,
    platform: str,
    app_version: Optional[str] = None,
    device_model: Optional[str] = None,
) -> DeviceToken:
    obj = db.execute(
        select(DeviceToken).where(DeviceToken.token == token)
    ).scalars().first()
    now = datetime.now(timezone.utc)
    if obj:
        obj.platform = platform
        if app_version is not None:
            obj.app_version = app_version
        if device_model is not None:
            obj.device_model = device_model
        obj.is_active = True
        obj.last_seen_at = now
    else:
        obj = DeviceToken(
            token=token,
            platform=platform,
            app_version=app_version,
            device_model=device_model,
            is_active=True,
            last_seen_at=now,
        )
        db.add(obj)
    db.commit()
    db.refresh(obj)
    return obj


def deactivate(db: Session, token: str) -> bool:
    res = db.execute(
        update(DeviceToken)
        .where(DeviceToken.token == token)
        .values(is_active=False)
    )
    db.commit()
    return (res.rowcount or 0) > 0


def list_active(db: Session, platforms: Optional[Sequence[str]] = None) -> List[DeviceToken]:
    stmt = select(DeviceToken).where(DeviceToken.is_active.is_(True))
    if platforms:
        stmt = stmt.where(DeviceToken.platform.in_(platforms))
    return db.execute(stmt).scalars().all()
