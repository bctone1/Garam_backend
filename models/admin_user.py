# models/admin_user
from sqlalchemy import Column, BigInteger, String, DateTime, func, Index
from database.base import Base

class AdminUser(Base):
    __tablename__ = "admin_user"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    name = Column(String, nullable=False)
    email = Column(String, unique=True, nullable=False)
    department = Column(String, nullable=False)
    password = Column(String(128), nullable=False)  # 해시된 비밀번호 저장

    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)

    __table_args__ = (
        Index("idx_admin_user_email", "email"),
        Index("idx_admin_user_created", "created_at"),
    )
