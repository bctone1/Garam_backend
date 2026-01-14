# models/inquiry.py

from sqlalchemy import (
    Column,
    BigInteger,
    String,
    Text,
    DateTime,
    ForeignKey,
    func,
    CheckConstraint,
    Index,
)
from sqlalchemy.orm import relationship
from database.base import Base


class Inquiry(Base):
    __tablename__ = "inquiry"

    id = Column(BigInteger, primary_key=True, autoincrement=True)

    # ✅ 최종 네이밍
    # - customer_name -> business_name (NOT NULL)
    # - company -> business_number (NULL)
    business_name = Column(String, nullable=False)
    business_number = Column(String, nullable=True)

    phone = Column(String)
    content = Column(Text, nullable=False)

    inquiry_type = Column(String, nullable=False, server_default="other")
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

    attachments = relationship(
        "InquiryAttachment",
        back_populates="inquiry",
        cascade="all, delete-orphan",
        order_by="InquiryAttachment.id.asc()",
    )

    __table_args__ = (
        CheckConstraint(
            "status IN ('new','processing','on_hold','completed')",
            name="chk_inquiry_status",
        ),
        CheckConstraint(
            "inquiry_type IN ('paper_request','sales_report','kiosk_menu_update','other')",
            name="chk_inquiry_type",
        ),
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
        Index("idx_inquiry_type_created", "inquiry_type", "created_at"),
        # 필요하면 검색용(선택)
        Index("idx_inquiry_business_name_created", "business_name", "created_at"),
    )


class InquiryAttachment(Base):
    __tablename__ = "inquiry_attachment"

    id = Column(BigInteger, primary_key=True, autoincrement=True)

    inquiry_id = Column(
        BigInteger,
        ForeignKey("inquiry.id", ondelete="CASCADE"),
        nullable=False,
    )

    storage_type = Column(String, nullable=False, server_default="local")  # local | s3
    storage_key = Column(String, nullable=False)  # local relative path or s3 key
    original_name = Column(String)
    content_type = Column(String)
    size_bytes = Column(BigInteger)

    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    inquiry = relationship("Inquiry", back_populates="attachments")

    __table_args__ = (
        CheckConstraint(
            "storage_type IN ('local','s3')",
            name="chk_inqa_storage_type",
        ),
        CheckConstraint(
            "content_type IS NULL OR content_type LIKE 'image/%'",
            name="chk_inqa_content_type_image",
        ),
        Index("idx_inqa_inquiry_time", "inquiry_id", "created_at"),
        Index("idx_inqa_inquiry", "inquiry_id"),
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
            name="chk_inqh_action",
        ),
        Index("idx_inqh_inquiry_time", "inquiry_id", "created_at"),
        Index("idx_inqh_action_time", "action", "created_at"),
    )


__all__ = ["Inquiry", "InquiryHistory", "InquiryAttachment"]
