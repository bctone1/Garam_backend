# models/faq.py
from sqlalchemy import (
    Column, BigInteger, Text, Integer, DateTime, Numeric,
    CheckConstraint, Index, func, text, ForeignKey
)
from sqlalchemy.orm import relationship
from database.base import Base


class FAQ(Base):
    __tablename__ = "faq"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    question = Column(Text, nullable=False)
    answer = Column(Text, nullable=False)
    views = Column(Integer, nullable=False, server_default=text("0"))
    quick_category_id = Column(
        BigInteger,
        ForeignKey("quick_category.id", ondelete="SET NULL"),
        nullable=True
    )
    satisfaction_rate = Column(Numeric(5, 2), nullable=False, server_default=text("0"))
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)

    # 조인 응답용
    quick_category = relationship("QuickCategory", passive_deletes=True)

    __table_args__ = (
        CheckConstraint("views >= 0", name="chk_faq_views_nonneg"),
        CheckConstraint("satisfaction_rate >= 0 AND satisfaction_rate <= 100", name="chk_faq_rate_range"),
        Index("idx_faq_created", created_at.desc()),
        Index("idx_faq_qc", "quick_category_id"),
        # pg_trgm 확장 필요(FAQ 찾기에서 검색 빠르게 할때 사용)
        Index("gin_trgm_faq_question", text("lower(question) gin_trgm_ops"), postgresql_using="gin"),
    )


__all__ = ["FAQ"]
