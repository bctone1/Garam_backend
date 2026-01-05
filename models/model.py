# models/model.py
from sqlalchemy import (
    Column, BigInteger, Text, Integer, Boolean, DateTime, Numeric,
    CheckConstraint, Index, func, text)
from database.base import Base


class Model(Base):
    __tablename__ = "model"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    name = Column(Text, nullable=False)

    # 성능 지표
    accuracy = Column(Numeric(5, 2), nullable=False, server_default=text("0"))
    avg_response_time_ms = Column(Integer, nullable=False, server_default=text("0"))
    month_conversations = Column(Integer, nullable=False, server_default=text("0"))
    uptime_percent = Column(Numeric(5, 2), nullable=False, server_default=text("0"))

    # 응답 스타일 설정
    response_style = Column(Text, nullable=False, server_default=text("'professional'"))

    # 응답 품질 설정
    block_inappropriate = Column(Boolean, nullable=False, server_default=text("true"))
    restrict_non_tech = Column(Boolean, nullable=False, server_default=text("true"))
    fast_response_mode = Column(Boolean, nullable=False, server_default=text("true"))
    suggest_agent_handoff = Column(Boolean, nullable=False, server_default=text("true"))

    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)

    __table_args__ = (
        CheckConstraint(
            "response_style IN ('professional','friendly','concise')",
            name="chk_model_response_style"
        ),
    )


