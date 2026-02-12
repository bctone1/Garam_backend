# crud/customer.py
from __future__ import annotations

import re
from typing import Optional, List, Dict, Any

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from models.customer import Customer


def clean_business_number(val: Any) -> Optional[str]:
    """사업자번호에서 숫자만 추출 (대시/공백 등 제거)."""
    if not val:
        return None
    cleaned = re.sub(r"[^0-9]", "", str(val))
    return cleaned or None


def get_by_business_number(db: Session, business_number: str) -> Optional[Customer]:
    """사업자번호(숫자만)로 고객 조회."""
    cleaned = clean_business_number(business_number)
    if not cleaned:
        return None
    stmt = select(Customer).where(Customer.business_number == cleaned)
    return db.execute(stmt).scalars().first()


def create(db: Session, data: Dict[str, Any]) -> Customer:
    """단건 고객 등록."""
    obj = Customer(
        business_number=clean_business_number(data.get("business_number")),
        business_name=data["business_name"],
        phone=data.get("phone"),
        address=data.get("address"),
    )
    db.add(obj)
    db.commit()
    db.refresh(obj)
    return obj


def bulk_create_from_csv(db: Session, rows: List[Dict[str, Any]]) -> List[Customer]:
    """
    CSV 일괄 등록. 한 트랜잭션으로 처리 (실패 시 전체 rollback).
    """
    created: List[Customer] = []
    for row in rows:
        obj = Customer(
            business_number=clean_business_number(row.get("business_number")),
            business_name=row["business_name"],
            phone=row.get("phone"),
            address=row.get("address"),
        )
        db.add(obj)
        created.append(obj)

    db.commit()
    return created


def search_by_keyword(
    db: Session, keyword: str, *, offset: int = 0, limit: int = 50
) -> List[Customer]:
    """사업자명 또는 사업자번호 ILIKE 부분 매칭 검색."""
    pattern = f"%{keyword}%"
    stmt = (
        select(Customer)
        .where(
            or_(
                Customer.business_name.ilike(pattern),
                Customer.business_number.ilike(pattern),
            )
        )
        .order_by(Customer.id.desc())
        .offset(offset)
        .limit(min(limit, 100))
    )
    return db.execute(stmt).scalars().all()


def list_customers(
    db: Session, *, offset: int = 0, limit: int = 50
) -> List[Customer]:
    stmt = (
        select(Customer)
        .order_by(Customer.id.desc())
        .offset(offset)
        .limit(min(limit, 100))
    )
    return db.execute(stmt).scalars().all()


def get(db: Session, customer_id: int) -> Optional[Customer]:
    return db.get(Customer, customer_id)


def delete(db: Session, customer_id: int) -> bool:
    obj = get(db, customer_id)
    if not obj:
        return False
    db.delete(obj)
    db.commit()
    return True


def update(db: Session, customer_id: int, data: Dict[str, Any]) -> Optional[Customer]:
    obj = get(db, customer_id)
    if not obj:
        return None

    if "business_number" in data:
        data["business_number"] = clean_business_number(data["business_number"])

    for k, v in data.items():
        setattr(obj, k, v)

    db.add(obj)
    db.commit()
    db.refresh(obj)
    return obj
