# models/device_token.py
"""푸시 알림용 디바이스 토큰 모델."""
from __future__ import annotations
from sqlalchemy import (
    Column, BigInteger, Text, Boolean, DateTime, String, Index, func, text,
)
from database.base import Base


class DeviceToken(Base):
    __tablename__ = "device_token"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    token = Column(Text, nullable=False, unique=True)
    platform = Column(String(16), nullable=False)  # 'android' | 'ios'
    app_version = Column(String(32), nullable=True)
    device_model = Column(String(128), nullable=True)
    is_active = Column(Boolean, nullable=False, server_default=text("true"))
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    last_seen_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    __table_args__ = (
        Index("idx_device_token_active", "is_active"),
        Index("idx_device_token_platform", "platform"),
    )


__all__ = ["DeviceToken"]
