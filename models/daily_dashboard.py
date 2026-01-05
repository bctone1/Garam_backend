# models/daily_dashboard.py
from __future__ import annotations
from sqlalchemy import Column, Date, DateTime, Integer, Numeric, SmallInteger, Index, func, text
from sqlalchemy.dialects.postgresql import JSONB
from database.base import Base

class DailyDashboard(Base):
    __tablename__ = "daily_dashboard"

    d = Column(Date, primary_key=True, comment="KST 기준 날짜")
    weekday = Column(SmallInteger, nullable=False, comment="ISO 1=월..7=일")

    sessions_total = Column(Integer, nullable=False, default=0)
    sessions_with_assistant = Column(Integer, nullable=False, default=0)
    sessions_resolved = Column(Integer, nullable=False, default=0)

    messages_total = Column(Integer, nullable=False, default=0)

    avg_response_ms = Column(Numeric(10, 2), nullable=False, default=0)

    # assistant  응답 지연 시간의 중앙값
    p50_response_ms = Column(Numeric(10, 2), nullable=False, default=0)

    # 간헐적 지연 탐지
    p90_response_ms = Column(Numeric(10, 2), nullable=False, default=0)

    avg_turns = Column(Numeric(6, 2), nullable=False, default=0)

    inquiries_created = Column(Integer, nullable=False, default=0)
    feedback_helpful = Column(Integer, nullable=False, default=0)
    feedback_not_helpful = Column(Integer, nullable=False, default=0)

    sessions_by_hour = Column(JSONB, nullable=False, server_default=text("'{}'::jsonb"))  # {"0":12,...}

    updated_at = Column(DateTime(timezone=True), nullable=False,
                        server_default=func.now(), onupdate=func.now())

    __table_args__ = (Index("idx_daily_dashboard_d_desc", d.desc()),)
