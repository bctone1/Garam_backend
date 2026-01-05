# models/chat.py
from sqlalchemy import (
    Column, BigInteger, String, Text, Integer, DateTime, Boolean,
    ForeignKey, func, CheckConstraint, Index, text
)
from sqlalchemy.orm import relationship
from sqlalchemy.dialects.postgresql import JSON
from pgvector.sqlalchemy import Vector
from database.base import Base


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

    role = Column(String, nullable=False)                 # 'user' | 'assistant'
    content = Column(Text, nullable=False)
    response_latency_ms = Column(Integer)                 # assistant 메시지에만 채움
    vector_memory = Column(Vector(1536), nullable=True)  # pgvector
    extra_data = Column(JSON, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    # 관계
    session = relationship(
        "ChatSession",
        back_populates="messages",
        passive_deletes=True,
    )

    __table_args__ = (
        CheckConstraint("role IN ('user','assistant')", name="chk_message_role"),
        CheckConstraint(
            "(role = 'user' AND response_latency_ms IS NULL) OR "
            "(role = 'assistant' AND (response_latency_ms IS NULL OR response_latency_ms >= 0))",
            name="chk_message_latency_rule",
        ),
        Index("idx_message_session_created", "session_id", "created_at"),
        Index("idx_message_role_created", "role", "created_at"),
    )


class Feedback(Base):
    __tablename__ = "feedback"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    session_id = Column(BigInteger, ForeignKey("chat_session.id", ondelete="CASCADE"))

    rating = Column(String, nullable=True)   # 'helpful' | 'not_helpful' | null
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    # 관계
    session = relationship("ChatSession", backref="feedbacks", passive_deletes=True)

    __table_args__ = (
        CheckConstraint("rating IN ('helpful','not_helpful')", name="chk_feedback_rating"),
                Index("idx_feedback_session", "session_id", "created_at"),
                Index("idx_feedback_created", "created_at"),
        Index("idx_feedback_rating_time", "rating", "created_at"),

        Index(
            "uq_feedback_session_once",
            "session_id",
            unique=True,
            postgresql_where=text("session_id IS NOT NULL"),
        ),
    )


__all__ = ["ChatSession", "Message", "Feedback"]
