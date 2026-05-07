# models/notice.py
from datetime import datetime, timezone
from sqlalchemy import (
    Column, BigInteger, Text, Boolean, DateTime,
    CheckConstraint, Index, ForeignKey, func, text,
)
from sqlalchemy.orm import relationship
from database.base import Base


class Notice(Base):
    __tablename__ = "notice"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    title = Column(Text, nullable=False)
    content = Column(Text, nullable=False)
    is_important = Column(Boolean, nullable=False, server_default=text("false"))
    author_admin_id = Column(
        BigInteger,
        ForeignKey("admin_user.id", ondelete="SET NULL"),
        nullable=True,
    )
    start_at = Column(DateTime(timezone=True), nullable=True)
    end_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)

    author = relationship("AdminUser", passive_deletes=True)

    __table_args__ = (
        CheckConstraint(
            "end_at IS NULL OR start_at IS NULL OR end_at > start_at",
            name="chk_notice_end_after_start",
        ),
        Index("idx_notice_created", created_at.desc()),
        Index("idx_notice_start_end", "start_at", "end_at"),
        Index("idx_notice_important", "is_important"),
    )

    @property
    def status(self) -> str:
        now = datetime.now(timezone.utc)
        if self.start_at and self.start_at > now:
            return "scheduled"
        if self.end_at and self.end_at <= now:
            return "expired"
        return "active"


__all__ = ["Notice"]
