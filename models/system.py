# models/system.py
from sqlalchemy import (
    Column, BigInteger, Integer, Text, DateTime, ForeignKey,
    CheckConstraint, Index, func, text)
from database.base import Base


class SystemSetting(Base):
    __tablename__ = "system_setting"

    id = Column(BigInteger, primary_key=True, autoincrement=True)

    welcome_title = Column(Text, nullable=False)
    welcome_message = Column(Text, nullable=False)

    operating_hours = Column(Text, nullable=False, server_default=text("'business'"))   # '24/7'|'business'|'extended'
    file_upload_mode = Column(Text, nullable=False, server_default=text("'true'"))      # 'true'|'images'|'false'
    session_duration = Column(Text, nullable=False, server_default=text("'60'"))        # '30'|'60'|'120'|'unlimited'
    max_messages = Column(Text, nullable=False, server_default=text("'30'"))            # '10'|'30'|'50'|'unlimited'

    emergency_phone = Column(Text, nullable=False)
    emergency_email = Column(Text, nullable=False)

    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)

    __table_args__ = (
        CheckConstraint("operating_hours IN ('24/7','business','extended')", name="chk_sys_operating_hours"),
        CheckConstraint("file_upload_mode IN ('true','images','false')", name="chk_sys_file_upload_mode"),
        CheckConstraint("session_duration IN ('30','60','120','unlimited')", name="chk_sys_session_duration"),
        CheckConstraint("max_messages IN ('10','30','50','unlimited')", name="chk_sys_max_messages"),
        Index("idx_system_setting_updated_at", updated_at.desc()),
    )


class QuickCategory(Base):
    __tablename__ = "quick_category"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    # setting_id = Column(BigInteger, ForeignKey("system_setting.id", ondelete="CASCADE"), nullable=False)

    icon_emoji = Column(Text, nullable=False)
    name = Column(Text, nullable=False)
    description = Column(Text)  # nullable
    sort_order = Column(Integer, nullable=False, server_default=text("0"))

    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)


    __table_args__ = (
        CheckConstraint("sort_order >= 0", name="chk_qc_sort_nonneg"),
        Index("idx_qc_order", "sort_order"),  # 필요하면 sort_order 단일 인덱스로 교체
    )

class QuickCategoryItem(Base):
    __tablename__ = "quick_category_item"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    quick_category_id = Column(
        BigInteger, ForeignKey(QuickCategory.id, ondelete="CASCADE"), nullable=False)
    name = Column(Text, nullable=False)
    description = Column(Text, nullable=True)


__all__ = ["SystemSetting", "QuickCategory", "QuickCategoryItem"]

