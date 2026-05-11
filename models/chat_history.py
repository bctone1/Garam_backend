# models/chat_history.py
from sqlalchemy import (
    Column,
    BigInteger,
    Integer,
    String,
    Text,
    Date,
    DateTime,
    Boolean,
    ForeignKey,
    UniqueConstraint,
    CheckConstraint,
    Index,
    func,
)
from sqlalchemy.orm import relationship
from sqlalchemy.dialects.postgresql import JSONB

from database.base import Base


# =========================
# 1) 세션 요약/분류(리스트 빠르게 뽑기용)
# =========================
class ChatSessionInsight(Base):
    __tablename__ = "chat_session_insight"

    session_id = Column(
        BigInteger,
        ForeignKey("chat_session.id", ondelete="CASCADE"),
        primary_key=True,
    )

    started_at = Column(DateTime(timezone=True), nullable=False)

    channel = Column(String(32), nullable=True)  # web/mobile/admin 등
    category = Column(String(64), nullable=True)  # 캐시용(표시용) name (선택)

    quick_category_id = Column(
        BigInteger,
        ForeignKey("quick_category.id", ondelete="SET NULL"),
        nullable=True,
    )

    status = Column(
        String(16), nullable=False, server_default="success"
    )  # success/failed/commit
    first_question = Column(Text, nullable=True)
    question_count = Column(Integer, nullable=False, server_default="0")
    failed_reason = Column(Text, nullable=True)

    created_at = Column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at = Column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    session = relationship("ChatSession", backref="insight", passive_deletes=True)
    quick_category = relationship("QuickCategory", passive_deletes=True)

    __table_args__ = (
        CheckConstraint(
            "status IN ('success','failed','commit')",
            name="chk_chat_s_insight_status",
        ),
        CheckConstraint("question_count >= 0", name="chk_chat_s_insight_qcount_nonneg"),
        Index("idx_chat_s_insight_started_at", "started_at"),
        Index("idx_chat_s_insight_status_started_at", "status", "started_at"),
        Index("idx_chat_s_insight_category_started_at", "category", "started_at"),
        Index("idx_chat_s_insight_channel_started_at", "channel", "started_at"),
        Index("idx_chat_s_insight_qc_started_at", "quick_category_id", "started_at"),
    )


# =========================
# 2) 질문만(= user 메시지) + 키워드/태그
# =========================
class ChatMessageInsight(Base):
    __tablename__ = "chat_message_insight"

    message_id = Column(
        BigInteger,
        ForeignKey("message.id", ondelete="CASCADE"),
        primary_key=True,
    )

    session_id = Column(
        BigInteger,
        ForeignKey("chat_session.id", ondelete="CASCADE"),
        nullable=False,
    )

    is_question = Column(Boolean, nullable=False, server_default="true")
    category = Column(String(64), nullable=True)
    keywords = Column(JSONB, nullable=True)

    created_at = Column(DateTime(timezone=True), nullable=False)

    session = relationship(
        "ChatSession", backref="message_insights", passive_deletes=True
    )
    message = relationship("Message", backref="insight", passive_deletes=True)

    __table_args__ = (
        Index("idx_chat_m_insight_session_created", "session_id", "created_at"),
        Index("idx_chat_m_insight_category_created", "category", "created_at"),
        Index("idx_chat_m_insight_is_question_created", "is_question", "created_at"),
    )


# =========================
# 3) 워드클라우드/키워드 통계(기간 집계 빠르게)
# =========================
class ChatKeywordDaily(Base):
    __tablename__ = "chat_keyword_daily"

    id = Column(BigInteger, primary_key=True, autoincrement=True)

    dt = Column(Date, nullable=False)
    keyword = Column(Text, nullable=False)
    count = Column(Integer, nullable=False, server_default="0")

    channel = Column(String(32), nullable=True)

    quick_category_id = Column(
        BigInteger,
        ForeignKey("quick_category.id", ondelete="SET NULL"),
        nullable=True,
    )

    updated_at = Column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    __table_args__ = (
        CheckConstraint("count >= 0", name="chk_chat_kw_daily_count_nonneg"),
        UniqueConstraint(
            "dt", "keyword", "channel", "quick_category_id", name="uq_chat_kw_daily"
        ),
        Index("idx_chat_kw_daily_dt", "dt"),
        Index("idx_chat_kw_daily_keyword", "keyword"),
        Index("idx_chat_kw_daily_dt_qc", "dt", "quick_category_id"),
        Index("idx_chat_kw_daily_dt_channel", "dt", "channel"),
    )


class KnowledgeSuggestion(Base):
    __tablename__ = "knowledge_suggestion"

    id = Column(BigInteger, primary_key=True, autoincrement=True)

    session_id = Column(
        BigInteger,
        ForeignKey("chat_session.id", ondelete="CASCADE"),
        nullable=False,
    )

    # message 1건당 suggestion 1건(멱등 upsert 핵심)
    message_id = Column(
        BigInteger,
        ForeignKey("message.id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
    )

    question_text = Column(Text, nullable=False)
    assistant_answer = Column(Text, nullable=True)
    final_answer = Column(Text, nullable=True)

    answer_status = Column(
        String(16), nullable=False, server_default="error"
    )  # ok/error
    review_status = Column(
        String(16), nullable=False, server_default="pending"
    )  # pending/ingested/deleted

    reason_code = Column(Text, nullable=True)
    retrieval_meta = Column(JSONB, nullable=True)

    target_knowledge_id = Column(
        BigInteger,
        ForeignKey("knowledge.id", ondelete="SET NULL"),
        nullable=True,
    )

    # ingest 결과로 생성/업서트된 chunk id (멱등/추적)
    ingested_chunk_id = Column(
        BigInteger,
        ForeignKey("knowledge_chunk.id", ondelete="SET NULL"),
        nullable=True,
    )

    ingested_at = Column(DateTime(timezone=True), nullable=True)
    deleted_at = Column(DateTime(timezone=True), nullable=True)

    created_at = Column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at = Column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    session = relationship("ChatSession", passive_deletes=True)
    message = relationship("Message", passive_deletes=True)
    target_knowledge = relationship("Knowledge", passive_deletes=True)
    ingested_chunk = relationship("KnowledgeChunk", passive_deletes=True)

    __table_args__ = (
        CheckConstraint(
            "answer_status IN ('ok','error')", name="chk_k_suggest_answer_status"
        ),
        CheckConstraint(
            "review_status IN ('pending','ingested','deleted')",
            name="chk_k_suggest_review_status",
        ),
        CheckConstraint(
            "(review_status <> 'ingested') OR (final_answer IS NOT NULL AND ingested_chunk_id IS NOT NULL)",
            name="chk_k_suggest_ingested_requires_answer_chunk",
        ),
        Index("idx_k_suggest_review_created", "review_status", "created_at"),
        Index("idx_k_suggest_session_created", "session_id", "created_at"),
        Index("idx_k_suggest_target_review", "target_knowledge_id", "review_status"),
        Index(
            "idx_k_suggest_answer_review_created",
            "answer_status",
            "review_status",
            "created_at",
        ),
    )


__all__ = [
    "ChatSessionInsight",
    "ChatMessageInsight",
    "ChatKeywordDaily",
    "KnowledgeSuggestion",
]
