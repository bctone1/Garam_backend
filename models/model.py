# SQLAlchemy ORM (물리설계 반영)

from sqlalchemy import (
    Column, BigInteger, Text, Integer, Boolean, DateTime, Numeric,
    CheckConstraint, Index, func, text
)
from sqlalchemy.dialects.postgresql import JSONB
from garam_backend.database.base import Base

class Model(Base):
    __tablename__ = "model"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    name = Column(Text, nullable=False)
    provider_name = Column(Text, nullable=False)
    description = Column(Text, nullable=False)
    features = Column(JSONB, nullable=False, server_default=text("'[]'::jsonb"))

    is_active = Column(Boolean, nullable=False, server_default=text("false"))
    status_text = Column(Text, nullable=False)

    accuracy = Column(Numeric(5, 2), nullable=False, server_default=text("0"))
    avg_response_time_ms = Column(Integer, nullable=False, server_default=text("0"))
    month_conversations = Column(Integer, nullable=False, server_default=text("0"))
    uptime_percent = Column(Numeric(5, 2), nullable=False, server_default=text("0"))

    response_style = Column(Text, nullable=False, server_default=text("'professional'"))
    block_inappropriate = Column(Boolean, nullable=False, server_default=text("false"))
    restrict_non_tech = Column(Boolean, nullable=False, server_default=text("false"))
    fast_response_mode = Column(Boolean, nullable=False, server_default=text("false"))
    suggest_agent_handoff = Column(Boolean, nullable=False, server_default=text("false"))

    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)

    __table_args__ = (
        CheckConstraint("response_style IN ('professional','friendly','concise')", name="chk_model_response_style"),
        # 활성 1개 보장(부분 유니크 인덱스)
        Index("uq_model_active_one", text("(true)"), unique=True, postgresql_where=text("is_active")),
        # 인덱스
        Index("idx_model_active", text("is_active DESC")),
        Index("idx_model_provider", "provider_name"),
        # 선택: 태그 검색(GIN)
        # Index("idx_model_features_gin", "features", postgresql_using="gin"),
    )

