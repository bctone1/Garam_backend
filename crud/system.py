# CRUD/system.py
from __future__ import annotations
from typing import Optional, Iterable
from sqlalchemy.orm import Session
from sqlalchemy import case, select
from models.system import SystemSetting, QuickCategory, QuickCategoryItem
from schemas.system import QuickCategoryCreate, QuickCategoryItemResponse


# ========== SystemSetting (싱글톤) ==========

def _get_latest_setting(db: Session) -> Optional[SystemSetting]:
    # updated_at DESC 인덱스 존재
    return (
        db.query(SystemSetting)
        .order_by(SystemSetting.updated_at.desc(), SystemSetting.id.desc())
        .first()
    )

def create_setting(db: Session, data: dict) -> SystemSetting:
    """
    싱글톤 정책: 기존 레코드가 있으면 '업데이트처럼' 덮어쓰고, 없으면 생성.
    엔드포인트는 항상 객체를 반환하길 기대하므로 예외 대신 upsert 방식으로 처리.
    """
    curr = _get_latest_setting(db)
    if curr:
        for key, value in data.items():
            if hasattr(curr, key) and value is not None:
                setattr(curr, key, value)
        db.add(curr)
        db.commit()
        db.refresh(curr)
        return curr

    obj = SystemSetting(**data)
    db.add(obj)
    db.commit()
    db.refresh(obj)
    return obj

def get_current_setting(db: Session) -> Optional[SystemSetting]:
    return _get_latest_setting(db)

def update_current_setting(db: Session, data: dict) -> Optional[SystemSetting]:
    obj = _get_latest_setting(db)
    if not obj:
        return None
    for key, value in data.items():
        if hasattr(obj, key) and value is not None:
            setattr(obj, key, value)
    db.add(obj)
    db.commit()
    db.refresh(obj)
    return obj

def delete_current_setting(db: Session) -> bool:
    obj = _get_latest_setting(db)
    if not obj:
        return False
    db.delete(obj)
    db.commit()
    return True


# ========== QuickCategory (여러 개) ==========

def list_quick_categories(db: Session, *, offset: int = 0, limit: int = 200):
    return (
        db.query(QuickCategory)
        .order_by(QuickCategory.sort_order.asc(), QuickCategory.id.asc())
        .offset(offset)
        .limit(limit)
        .all()
    )

def upsert_quick_categories(db: Session, payload_list: list[QuickCategoryCreate]):
    results = []

    for item in payload_list:
        data = item.model_dump()

        # ID가 있으면 기존 항목 업데이트
        if data.get("id"):
            existing = db.query(QuickCategory).filter(QuickCategory.id == data["id"]).first()
            if existing:
                for key, value in data.items():
                    if value is not None:
                        setattr(existing, key, value)
                db.add(existing)
                results.append(existing)
                continue

        # 새 항목인 경우 sort_order 자동 부여 후 생성
        if data.get("sort_order") is None:
            last = (
                db.query(QuickCategory.sort_order)
                .order_by(QuickCategory.sort_order.desc())
                .first()
            )
            data["sort_order"] = (last[0] + 1) if last else 0

        new_obj = QuickCategory(**data)
        db.add(new_obj)
        results.append(new_obj)

    db.commit()

    for obj in results:
        db.refresh(obj)

    return results


def create_quick_category(db: Session, data: dict) -> QuickCategory:
    # sort_order 미지정 시 가장 뒤로 보내기
    if data.get("sort_order") is None:
        last = (
            db.query(QuickCategory.sort_order)
            .order_by(QuickCategory.sort_order.desc())
            .first()
        )
        data["sort_order"] = (last[0] + 1) if last else 0

    obj = QuickCategory(**data)
    db.add(obj)
    db.commit()
    db.refresh(obj)
    return obj

def get_quick_category(db: Session, qc_id: int) -> Optional[QuickCategory]:
    return db.query(QuickCategory).get(qc_id)

def update_quick_category(db: Session, qc_id: int, data: dict) -> Optional[QuickCategory]:
    obj = db.query(QuickCategory).get(qc_id)
    if not obj:
        return None
    for key, value in data.items():
        if hasattr(obj, key) and value is not None:
            setattr(obj, key, value)
    db.add(obj)
    db.commit()
    db.refresh(obj)
    return obj

def delete_quick_category(db: Session, qc_id: int) -> bool:
    obj = db.query(QuickCategory).get(qc_id)
    if not obj:
        # return False #원래는 False가 맞는데 프론트화면에서 오류 발생하여 수정했습니다!
        return True
    db.delete(obj)
    db.commit()
    return True

def reorder_quick_categories(db: Session, ordered_ids: list[int]) -> int:
    """
    프론트에서 드래그앤드롭으로 정렬한 id 배열을 받으면,
    배열 순서대로 sort_order = 0..n-1 로 일괄 업데이트.
    """
    if not ordered_ids:
        return 0

    # CASE WHEN id=... THEN idx END
    case_expr = case(
        {id_: idx for idx, id_ in enumerate(ordered_ids)},
        value=QuickCategory.id,
        else_=QuickCategory.sort_order
    )
    q = db.query(QuickCategory).filter(QuickCategory.id.in_(ordered_ids))
    updated = q.update({QuickCategory.sort_order: case_expr}, synchronize_session=False)
    db.commit()
    return updated

def normalize_quick_category_order(db: Session) -> int:
    """
    sort_order가 중복/틈이 있을 수 있어 현재 정렬 기준(sort_order, id)로
    0..n-1로 재부여.
    """
    rows = (
        db.query(QuickCategory)
        .order_by(QuickCategory.sort_order.asc(), QuickCategory.id.asc())
        .all()
    )
    for idx, row in enumerate(rows):
        row.sort_order = idx
        db.add(row)
    db.commit()
    return len(rows)

# 생성 POST /system/quick-categories/{qc_id}/items
def create_quick_category_item(db: Session, qc_id: int, data: dict) -> QuickCategoryItem:
    obj = QuickCategoryItem(
        quick_category_id=qc_id,
        name=data.get("name"),
        description=data.get("description"),
    )
    db.add(obj)
    db.commit()
    db.refresh(obj)
    return obj

# 단건 조회 GET /system/quick-category-items/{item_id}
def get_quick_category_item(db: Session, item_id: int) -> QuickCategoryItem | None:
    return db.get(QuickCategoryItem, item_id)

# 카테고리 목록 GET /system/quick-categories/{qc_id}/items
def list_quick_category_items(db: Session, qc_id: int, offset: int = 0, limit: int = 100) -> list[QuickCategoryItem]:
    stmt = (
        select(QuickCategoryItem)
        .where(QuickCategoryItem.quick_category_id == qc_id)
        .offset(offset).limit(limit)
    )
    return list(db.scalars(stmt))

# 수정 PATCH /system/quick-category-items/{item_id}
def update_quick_category_item(db: Session, item_id: int, data: dict) -> QuickCategoryItem | None:
    obj = db.get(QuickCategoryItem, item_id)
    if not obj:
        return None
    if "name" in data: obj.name = data["name"]
    if "description" in data: obj.description = data["description"]
    db.commit()
    db.refresh(obj)
    return obj

# 삭제 DELETE /system/quick-category-items/{item_id}
def delete_quick_category_item(db: Session, item_id: int) -> bool:
    obj = db.get(QuickCategoryItem, item_id)
    if not obj:
        return False
    db.delete(obj)
    db.commit()
    return True


