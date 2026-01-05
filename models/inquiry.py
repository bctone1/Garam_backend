# models/inquiry

from sqlalchemy import (
    Column, BigInteger, String, Text, DateTime, ForeignKey,
    func, CheckConstraint, Index
)
from sqlalchemy.orm import relationship
from database.base import Base


class Inquiry(Base):
    __tablename__ = "inquiry"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    customer_name = Column(String, nullable=False)
    company = Column(String)
    phone = Column(String)
    content = Column(Text, nullable=False)
    status = Column(String, nullable=False, server_default="new")

    assignee_admin_id = Column(
        BigInteger,
        ForeignKey("admin_user.id", ondelete="SET NULL"),
        nullable=True,
    )

    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    assigned_at = Column(DateTime(timezone=True))
    completed_at = Column(DateTime(timezone=True))
    customer_satisfaction = Column(String)

    assignee = relationship(
        "AdminUser",
        backref="inquiries",
        foreign_keys=[assignee_admin_id],
    )
    histories = relationship(
        "InquiryHistory",
        back_populates="inquiry",
        cascade="all, delete-orphan",
        order_by="InquiryHistory.id.asc()",
    )

    __table_args__ = (
        CheckConstraint(
            "status IN ('new','processing','on_hold','completed')",
            name="chk_inquiry_status",
        ),
        # 담당자가 없어지면(SET NULL) assigned_at 이 남아 있어도 허용
        CheckConstraint(
            "assignee_admin_id IS NULL OR assigned_at IS NOT NULL",
            name="chk_inquiry_assignment_consistency",
        ),
        CheckConstraint(
            "status <> 'completed' OR completed_at IS NOT NULL",
            name="chk_inquiry_completion_consistency",
        ),
        CheckConstraint(
            "assigned_at IS NULL OR assigned_at >= created_at",
            name="chk_inquiry_assigned_after_created",
        ),
        CheckConstraint(
            "completed_at IS NULL OR completed_at >= COALESCE(assigned_at, created_at)",
            name="chk_inquiry_completed_after_assigned",
        ),
        CheckConstraint(
            "customer_satisfaction IS NULL OR customer_satisfaction IN ('satisfied','unsatisfied')",
            name="chk_inquiry_customer_satisfaction",
        ),
        Index("idx_inquiry_status_created", "status", "created_at"),
        Index("idx_inquiry_assignee_status", "assignee_admin_id", "status", "created_at"),
        Index("idx_inquiry_created", "created_at"),
    )


class InquiryHistory(Base):
    __tablename__ = "inquiry_history"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    inquiry_id = Column(BigInteger, ForeignKey("inquiry.id", ondelete="CASCADE"), nullable=False)
    action = Column(String, nullable=False)
    admin_name = Column(String)
    details = Column(Text)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    inquiry = relationship("Inquiry", back_populates="histories")


    __table_args__ = (
        CheckConstraint(
            "action IN ('new','assign','on_hold','resume','transfer','complete','note','contact','delete')",
            name="chk_inqh_action"
        ),

        Index("idx_inqh_inquiry_time", "inquiry_id", "created_at"),
        Index("idx_inqh_action_time", "action", "created_at"),

    )

__all__ = ["Inquiry", "InquiryHistory"]
