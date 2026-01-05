# MODELS/api_cost.py
from __future__ import annotations
from sqlalchemy import (
    Column, Date, Text, BigInteger, Numeric,
    Index, CheckConstraint, DateTime, func, PrimaryKeyConstraint
)
from database.base import Base


class ApiCostDaily(Base):
    __tablename__ = "api_cost_daily"

    # PK: KST 기준 일자 × 제품 × 모델
    d = Column(Date, nullable=False, comment="KST 기준 날짜")
    product = Column(Text, nullable=False, comment="llm | embedding | stt ")
    model = Column(Text, nullable=False, comment="예: gpt-4o-mini, text-embedding-3-small")

    # 사용량
    llm_tokens = Column(BigInteger, nullable=False, server_default=func.cast(0, BigInteger))
    embedding_tokens = Column(BigInteger, nullable=False, server_default=func.cast(0, BigInteger))
    audio_seconds = Column(BigInteger, nullable=False, server_default=func.cast(0, BigInteger))

    # 비용
    cost_usd = Column(Numeric(12, 6), nullable=False, server_default=func.cast(0, Numeric(12, 6)))

    # 메타
    updated_at = Column(DateTime(timezone=True), nullable=False,
                        server_default=func.now(), onupdate=func.now())

    __table_args__ = (
        PrimaryKeyConstraint("d", "product", "model", name="pk_api_cost_daily"),
        CheckConstraint("llm_tokens >= 0 AND embedding_tokens >= 0 AND audio_seconds >= 0", name="chk_api_cost_nonneg_usage"),
        CheckConstraint("cost_usd >= 0", name="chk_api_cost_nonneg_cost"),
        Index("idx_api_cost_daily_d_desc", d.desc()),
        Index("idx_api_cost_daily_d_product", d, product),
        Index("idx_api_cost_daily_product_model", product, model),
    )
