# SQLAlchemy ORM (물리설계 반영): chat_session, message, feedback

from sqlalchemy import (
    Column, BigInteger, String, Text, Integer, DateTime, Boolean,
    ForeignKey, func, CheckConstraint, Index, text
)
from sqlalchemy.orm import relationship
from sqlalchemy.dialects.postgresql import JSON
from pgvector.sqlalchemy import Vector
from garam_backend.database.base import Base


class ChatSession(Base):
    __tablename__ = "chat_session"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    title = Column(String(255), nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    ended_at = Column(DateTime(timezone=True))
    preview = Column(Text)
    resolved = Column(Boolean, server_default=text("false"), nullable=False)

    model_id = Column(BigInteger, ForeignKey("model.id", ondelete="SET NULL"))

    # 관계
    model = relationship("Model", backref="chat_sessions")
    messages = relationship(
        "Message",
        back_populates="session",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )

    __table_args__ = (
        CheckConstraint("ended_at IS NULL OR ended_at >= created_at", name="chk_chat_session_time"),
        Index("idx_chat_session_started_at", created_at.desc()),
        Index("idx_chat_session_model_id", "model_id"),
        Index("idx_chat_session_resolved_started", "resolved", created_at.desc()),
    )


class Message(Base):
    __tablename__ = "message"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    session_id = Column(BigInteger, ForeignKey("chat_session.id", ondelete="CASCADE"), nullable=False)

    role = Column(String, nullable=False)                 # 'user' | 'bot'
    content = Column(Text, nullable=False)
    response_latency_ms = Column(Integer)                 # bot 메시지에만 채움
    vector_memory = Column(Vector(1536), nullable=False)  # pgvector
    extra_data = Column(JSON)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    # 관계
    session = relationship(
        "ChatSession",
        back_populates="messages",
        passive_deletes=True,
    )

    __table_args__ = (
        CheckConstraint("role IN ('user','bot')", name="chk_message_role"),
        CheckConstraint(
            "(role = 'user' AND response_latency_ms IS NULL) OR "
            "(role = 'bot' AND (response_latency_ms IS NULL OR response_latency_ms >= 0))",
            name="chk_message_latency_rule",
        ),
        Index("idx_message_session_created", "session_id", "created_at"),
        Index("idx_message_role_created", "role", "created_at"),
        # 선택: pg_trgm 설치 시 텍스트 검색 가속
        # Index("idx_message_content_trgm", text("lower(content)"), postgresql_using="gin"),
    )


class Feedback(Base):
    __tablename__ = "feedback"

    id = Column(BigInteger, primary_key=True, autoincrement=True)

    session_id = Column(BigInteger, ForeignKey("chat_session.id", ondelete="CASCADE"))
    message_id = Column(BigInteger, ForeignKey("message.id", ondelete="CASCADE"))

    rating = Column(String, nullable=False)   # 'helpful' | 'not_helpful'
    comment = Column(Text)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    # 관계
    session = relationship("ChatSession", backref="feedbacks", passive_deletes=True)
    message = relationship("Message", backref="feedback", passive_deletes=True)

    __table_args__ = (
        CheckConstraint("rating IN ('helpful','not_helpful')", name="chk_feedback_rating"),
        CheckConstraint(
            "(session_id IS NOT NULL) <> (message_id IS NOT NULL)",
            name="chk_feedback_anchor_xor",
        ),
        Index("idx_feedback_session", "session_id", "created_at"),
        Index("idx_feedback_message", "message_id"),
        Index("idx_feedback_created", "created_at"),
        Index("idx_feedback_rating_time", "rating", "created_at"),
        Index(
            "uq_feedback_message_once",
            "message_id",
            unique=True,
            postgresql_where=text("message_id IS NOT NULL"),
        ),
        Index(
            "uq_feedback_session_once",
            "session_id",
            unique=True,
            postgresql_where=text("session_id IS NOT NULL"),
        ),
    )


__all__ = ["ChatSession", "Message", "Feedback"]
