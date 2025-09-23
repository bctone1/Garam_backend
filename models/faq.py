from sqlalchemy import (
    Column, BigInteger, Text, Integer, DateTime, Numeric,
    CheckConstraint, Index, func, text
)
from garam_backend.database.base import Base


class FAQ(Base):
    __tablename__ = "faq"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    question = Column(Text, nullable=False)
    answer = Column(Text, nullable=False)
    views = Column(Integer, nullable=False, server_default=text("0"))
    satisfaction_rate = Column(Numeric(5, 2), nullable=False, server_default=text("0"))
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)

    __table_args__ = (
        CheckConstraint("views >= 0", name="chk_faq_views_nonneg"),
        CheckConstraint("satisfaction_rate >= 0 AND satisfaction_rate <= 100", name="chk_faq_rate_range"),
        Index("idx_faq_created", created_at.desc()),
        # pg_trgm 확장 설치 후 GIN + trigram 인덱스
        Index("gin_trgm_faq_question", text("lower(question) gin_trgm_ops"), postgresql_using="gin"),
        # 필요 시 답변 본문에도 trigram 인덱스 추가 가능
        # Index("gin_trgm_faq_answer", text("lower(answer) gin_trgm_ops"), postgresql_using="gin"),
    )


__all__ = ["FAQ"]
