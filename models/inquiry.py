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

    # =========================
    # NEW: assignment/completion attribution
    # =========================
    # 최근 할당/위임을 누가 했는지(대표=0 포함)
    assigned_by_admin_id = Column(
        BigInteger,
        ForeignKey("admin_user.id", ondelete="SET NULL"),
        nullable=True,
    )

    # 대표가 "처음 위임"한 건이면 0을 한 번 찍고 유지 (대표관리자 id=0 고정)
    delegated_from_admin_id = Column(
        BigInteger,
        ForeignKey("admin_user.id", ondelete="SET NULL"),
        nullable=True,
    )

    # 완료 처리한 관리자
    completed_by_admin_id = Column(
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

    assigned_by = relationship(
        "AdminUser",
        foreign_keys=[assigned_by_admin_id],
    )

    delegated_from = relationship(
        "AdminUser",
        foreign_keys=[delegated_from_admin_id],
    )

    completed_by = relationship(
        "AdminUser",
        foreign_keys=[completed_by_admin_id],
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
        # 할당 일관성: assignee가 있으면 assigned_at도 있어야 함
        CheckConstraint(
            "assignee_admin_id IS NULL OR assigned_at IS NOT NULL",
            name="chk_inquiry_assignment_consistency",
        ),
        # NEW: assignee가 있으면 assigned_by도 있어야 함(누가 위임했는지)
        CheckConstraint(
            "assignee_admin_id IS NULL OR assigned_by_admin_id IS NOT NULL",
            name="chk_inquiry_assigned_by_required",
        ),
        # NEW: delegated_from은 null 또는 0만 허용(대표관리자 id=0 고정 룰)
        CheckConstraint(
            "delegated_from_admin_id IS NULL OR delegated_from_admin_id = 0",
            name="chk_inquiry_delegated_from_rep_only",
        ),
        # 완료 일관성: completed면 completed_at 있어야 함
        CheckConstraint(
            "status <> 'completed' OR completed_at IS NOT NULL",
            name="chk_inquiry_completion_consistency",
        ),
        # NEW: completed면 completed_by도 있어야 함
        CheckConstraint(
            "status <> 'completed' OR completed_by_admin_id IS NOT NULL",
            name="chk_inquiry_completed_by_required",
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
        # 필요하면 검색용
        Index("idx_inquiry_business_name_created", "business_name", "created_at"),
        # NEW: 알림/분기 로직에 자주 쓰일 수 있는 컬럼들(필요 최소만)
        Index("idx_inquiry_assigned_by_created", "assigned_by_admin_id", "created_at"),
        Index("idx_inquiry_delegated_from_created", "delegated_from_admin_id", "created_at"),
        Index("idx_inquiry_completed_by_created", "completed_by_admin_id", "created_at"),
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


# =========================
# NEW: notification
# =========================
class Notification(Base):
    __tablename__ = "notification"

    id = Column(BigInteger, primary_key=True, autoincrement=True)

    recipient_admin_id = Column(
        BigInteger,
        ForeignKey("admin_user.id", ondelete="CASCADE"),
        nullable=False,
    )

    event_type = Column(String, nullable=False)

    inquiry_id = Column(
        BigInteger,
        ForeignKey("inquiry.id", ondelete="CASCADE"),
        nullable=False,
    )

    actor_admin_id = Column(
        BigInteger,
        ForeignKey("admin_user.id", ondelete="SET NULL"),
        nullable=True,
    )

    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    read_at = Column(DateTime(timezone=True), nullable=True)

    recipient = relationship("AdminUser", foreign_keys=[recipient_admin_id])
    actor = relationship("AdminUser", foreign_keys=[actor_admin_id])
    inquiry = relationship("Inquiry", foreign_keys=[inquiry_id])

    __table_args__ = (
        CheckConstraint(
            "event_type IN ('inquiry_new','inquiry_assigned','inquiry_completed')",
            name="chk_notification_event_type",
        ),
        Index(
            "idx_notification_recipient_read_created",
            "recipient_admin_id",
            "read_at",
            "created_at",
        ),
        Index("idx_notification_inquiry_created", "inquiry_id", "created_at"),
    )


__all__ = ["Inquiry", "InquiryHistory", "InquiryAttachment", "Notification"]
