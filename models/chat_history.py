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

    # chat_session 1:1 (PK=FK)
    session_id = Column(
        BigInteger,
        ForeignKey("chat_session.id", ondelete="CASCADE"),
        primary_key=True,
    )

    # 시간 필터를 join 없이 하려고 세션 시작 시각을 복제 저장(권장)
    started_at = Column(DateTime(timezone=True), nullable=False)

    channel = Column(String(32), nullable=True)   # web/mobile/admin 등
    category = Column(String(64), nullable=True)  # 캐시용(표시용) name (선택)

    # quick_category FK (권장: name 변경에도 정합성 유지)
    quick_category_id = Column(
        BigInteger,
        ForeignKey("quick_category.id", ondelete="SET NULL"),
        nullable=True,
    )

    status = Column(String(16), nullable=False, server_default="success")  # success/failed
    first_question = Column(Text, nullable=True)
    question_count = Column(Integer, nullable=False, server_default="0")
    failed_reason = Column(Text, nullable=True)

    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)

    # 관계(선택)
    session = relationship("ChatSession", backref="insight", passive_deletes=True)
    quick_category = relationship("QuickCategory", passive_deletes=True)

    __table_args__ = (
        CheckConstraint("status IN ('success','failed')", name="chk_chat_s_insight_status"),
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

    # message 1:1 (PK=FK)
    message_id = Column(
        BigInteger,
        ForeignKey("message.id", ondelete="CASCADE"),
        primary_key=True,
    )

    # 조회 편의(세션 단위 필터/집계용)
    session_id = Column(
        BigInteger,
        ForeignKey("chat_session.id", ondelete="CASCADE"),
        nullable=False,
    )

    # 질문 여부(기본은 user면 true로 잡고, 시스템/기타 케이스만 false)
    is_question = Column(Boolean, nullable=False, server_default="true")

    # 메시지 단위 분류가 필요하면 사용(없으면 null로 두고 세션 category만 써도 됨)
    category = Column(String(64), nullable=True)

    # 키워드 리스트: ["용지", "주문", ...]
    keywords = Column(JSONB, nullable=True)

    # 시간 필터를 join 없이 하려고 메시지 시각 복제 저장(권장)
    created_at = Column(DateTime(timezone=True), nullable=False)

    # 관계(선택)
    session = relationship("ChatSession", backref="message_insights", passive_deletes=True)
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

    dt = Column(Date, nullable=False)          # 집계 기준 날짜
    keyword = Column(Text, nullable=False)     # 키워드 원문
    count = Column(Integer, nullable=False, server_default="0")

    channel = Column(String(32), nullable=True)

    # quick_category FK (category 문자열 컬럼 제거)
    quick_category_id = Column(
        BigInteger,
        ForeignKey("quick_category.id", ondelete="SET NULL"),
        nullable=True,
    )

    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)

    __table_args__ = (
        CheckConstraint("count >= 0", name="chk_chat_kw_daily_count_nonneg"),
        UniqueConstraint("dt", "keyword", "channel", "quick_category_id", name="uq_chat_kw_daily"),
        Index("idx_chat_kw_daily_dt", "dt"),
        Index("idx_chat_kw_daily_keyword", "keyword"),
        Index("idx_chat_kw_daily_dt_qc", "dt", "quick_category_id"),
        Index("idx_chat_kw_daily_dt_channel", "dt", "channel"),
    )


__all__ = ["ChatSessionInsight", "ChatMessageInsight", "ChatKeywordDaily"]
