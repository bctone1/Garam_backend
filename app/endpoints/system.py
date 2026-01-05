# app/endpoints/system.py

from __future__ import annotations
from typing import List
from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel
from sqlalchemy.orm import Session

from database.session import get_db
from crud import system as crud
from schemas.system import (
    SystemSettingCreate, SystemSettingUpdate, SystemSettingResponse,
    QuickCategoryCreate, QuickCategoryUpdate, QuickCategoryResponse, QuickCategoryItemResponse, QuickCategoryItemCreate,
    QuickCategoryItemUpdate,
)

router = APIRouter(prefix="/system", tags=["System"])


# ===== SystemSetting (단일 운영값) =====
@router.post("/setting", response_model=SystemSettingResponse, status_code=status.HTTP_201_CREATED)
def create_setting(payload: SystemSettingCreate, db: Session = Depends(get_db)):
    return crud.create_setting(db, payload.model_dump())


@router.get("/setting", response_model=SystemSettingResponse)
def get_current_setting(db: Session = Depends(get_db)):
    obj = crud.get_current_setting(db)
    if not obj:
        raise HTTPException(status_code=404, detail="not found")
    return obj


@router.patch("/setting", response_model=SystemSettingResponse)
def update_current_setting(payload: SystemSettingUpdate, db: Session = Depends(get_db)):
    obj = crud.update_current_setting(db, payload.model_dump(exclude_unset=True))
    if not obj:
        raise HTTPException(status_code=404, detail="not found")
    return obj


@router.delete("/setting", status_code=status.HTTP_204_NO_CONTENT)
def delete_current_setting(db: Session = Depends(get_db)):
    if not crud.delete_current_setting(db):
        raise HTTPException(status_code=404, detail="not found")
    return None


# ===== QuickCategory (전역) =====
@router.get("/quick-categories", response_model=List[QuickCategoryResponse])
def list_quick_categories(
    offset: int = Query(0, ge=0),
    limit: int = Query(200, ge=1, le=1000),
    db: Session = Depends(get_db),
):
    return crud.list_quick_categories(db, offset=offset, limit=limit)

@router.post(
    "/quick-categories-list",
    response_model=List[QuickCategoryResponse],
    status_code=status.HTTP_201_CREATED
)
def upsert_quick_categories(payload: List[QuickCategoryCreate], db: Session = Depends(get_db)):
    return crud.upsert_quick_categories(db, payload)


@router.post("/quick-categories", response_model=QuickCategoryResponse, status_code=status.HTTP_201_CREATED)
def create_quick_category(payload: QuickCategoryCreate, db: Session = Depends(get_db)):
    return crud.create_quick_category(db, payload.model_dump())


@router.get("/quick-categories/{qc_id}", response_model=QuickCategoryResponse)
def get_quick_category(qc_id: int, db: Session = Depends(get_db)):
    obj = crud.get_quick_category(db, qc_id)
    if not obj:
        raise HTTPException(status_code=404, detail="not found")
    return obj


@router.patch("/quick-categories/{qc_id}", response_model=QuickCategoryResponse)
def update_quick_category(qc_id: int, payload: QuickCategoryUpdate, db: Session = Depends(get_db)):
    obj = crud.update_quick_category(db, qc_id, payload.model_dump(exclude_unset=True))
    if not obj:
        raise HTTPException(status_code=404, detail="not found")
    return obj


@router.delete("/quick-categories/{qc_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_quick_category(qc_id: int, db: Session = Depends(get_db)):
    if not crud.delete_quick_category(db, qc_id):
        raise HTTPException(status_code=404, detail="not found")
    return None


class ReorderIn(BaseModel):
    ordered_ids: List[int]


@router.post("/quick-categories/reorder")
def reorder_quick_categories(payload: ReorderIn, db: Session = Depends(get_db)):
    n = crud.reorder_quick_categories(db, payload.ordered_ids)
    return {"updated": n}


@router.post("/quick-categories/normalize")
def normalize_quick_category_order(db: Session = Depends(get_db)):
    n = crud.normalize_quick_category_order(db)
    return {"normalized": n}


# 생성
@router.post("/quick-categories/{qc_id}/items", response_model=QuickCategoryItemResponse)
def create_item(qc_id: int, payload: QuickCategoryItemCreate, db: Session = Depends(get_db)):
    return crud.create_quick_category_item(db, qc_id, payload.model_dump())

# 단건 조회
@router.get("/quick-category-items/{item_id}", response_model=QuickCategoryItemResponse)
def get_item(item_id: int, db: Session = Depends(get_db)):
    obj = crud.get_quick_category_item(db, item_id)
    if not obj: raise HTTPException(404)
    return obj


# 세부 카테고리(아이템) 목록
@router.get("/quick-categories/{qc_id}/items", response_model=list[QuickCategoryItemResponse])
def list_items(qc_id: int, db: Session = Depends(get_db)):
    return crud.list_quick_category_items(db, qc_id)

# 수정
@router.patch("/quick-category-items/{item_id}", response_model=QuickCategoryItemResponse)
def update_item(item_id: int, payload: QuickCategoryItemUpdate, db: Session = Depends(get_db)):
    obj = crud.update_quick_category_item(db, item_id, payload.model_dump(exclude_unset=True))
    if not obj: raise HTTPException(404)
    return obj

# 삭제
@router.delete("/quick-category-items/{item_id}", response_model=bool)
def delete_item(item_id: int, db: Session = Depends(get_db)):
    ok = crud.delete_quick_category_item(db, item_id)
    if not ok: raise HTTPException(404)
    return True








