from __future__ import annotations
from typing import Optional, List, Dict, Any
from sqlalchemy import select
from sqlalchemy.orm import Session
from models.system import SystemSetting, QuickCategory


# =========================
# SystemSetting
# =========================
def create_setting(db: Session, data: Dict[str, Any]) -> SystemSetting:
    obj = SystemSetting(**data)
    db.add(obj)
    db.commit()
    db.refresh(obj)
    return obj


def get_current_setting(db: Session) -> Optional[SystemSetting]:
    stmt = select(SystemSetting).order_by(SystemSetting.updated_at.desc()).limit(1)
    return db.execute(stmt).scalar_one_or_none()


def list_settings(db: Session, *, offset: int = 0, limit: int = 50) -> List[SystemSetting]:
    stmt = (
        select(SystemSetting)
        .order_by(SystemSetting.updated_at.desc())
        .offset(offset)
        .limit(min(limit, 100))
    )
    return db.execute(stmt).scalars().all()


def update_current_setting(db: Session, data: Dict[str, Any]) -> Optional[SystemSetting]:
    obj = get_current_setting(db)
    if not obj:
        return None
    for k, v in data.items():
        setattr(obj, k, v)
    db.add(obj)
    db.commit()
    db.refresh(obj)
    return obj


def delete_current_setting(db: Session) -> bool:
    obj = get_current_setting(db)
    if not obj:
        return False
    db.delete(obj)
    db.commit()
    return True


# =========================
# QuickCategory
# =========================
def get_quick_category(db: Session, qc_id: int) -> Optional[QuickCategory]:
    return db.get(QuickCategory, qc_id)


def list_quick_categories(db: Session, *, offset: int = 0, limit: int = 200) -> List[QuickCategory]:
    stmt = (
        select(QuickCategory)
        .order_by(QuickCategory.sort_order.asc(), QuickCategory.created_at.asc())
        .offset(offset)
        .limit(min(limit, 1000))
    )
    return db.execute(stmt).scalars().all()


def create_quick_category(db: Session, data: Dict[str, Any]) -> QuickCategory:
    obj = QuickCategory(**data)
    db.add(obj)
    db.commit()
    db.refresh(obj)
    return obj


def update_quick_category(db: Session, qc_id: int, data: Dict[str, Any]) -> Optional[QuickCategory]:
    obj = get_quick_category(db, qc_id)
    if not obj:
        return None
    for k, v in data.items():
        setattr(obj, k, v)
    db.add(obj)
    db.commit()
    db.refresh(obj)
    return obj


def delete_quick_category(db: Session, qc_id: int) -> bool:
    obj = get_quick_category(db, qc_id)
    if not obj:
        return False
    db.delete(obj)
    db.commit()
    return True


# 정렬 유틸: 주어진 ID 순서대로 0..N-1 재배치
def reorder_quick_categories(db: Session, ordered_ids: List[int]) -> int:
    rows = list_quick_categories(db, offset=0, limit=10_000)
    id2obj = {r.id: r for r in rows}
    n = 0
    for idx, qc_id in enumerate(ordered_ids):
        obj = id2obj.get(qc_id)
        if obj:
            obj.sort_order = idx
            db.add(obj)
            n += 1
    db.commit()
    return n


# 누락된 항목 순서 보정(현재 sort_order 기준으로 0..N-1 재번호)
def normalize_quick_category_order(db: Session) -> int:
    rows = list_quick_categories(db, offset=0, limit=10_000)
    for i, r in enumerate(rows):
        if r.sort_order != i:
            r.sort_order = i
            db.add(r)
    db.commit()
    return len(rows)
