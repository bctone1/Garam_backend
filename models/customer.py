# models/customer.py
from sqlalchemy import Column, BigInteger, String, DateTime, func
from database.base import Base


class Customer(Base):
    __tablename__ = "customer"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    business_number = Column(String, nullable=True)   # 숫자만 저장 (대시/공백 제거)
    business_name = Column(String, nullable=False)
    phone = Column(String, nullable=True)
    address = Column(String, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())


__all__ = ["Customer"]
