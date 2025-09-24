# FastAPI 라우터

from __future__ import annotations
from typing import Optional, List
from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel
from sqlalchemy.orm import Session

from database.session import get_db
from crud import system as crud
from schemas.system import (
    SystemSettingCreate, SystemSettingUpdate, SystemSettingResponse,
    QuickCategoryCreate, QuickCategoryUpdate, QuickCategoryResponse,
)

router = APIRouter(prefix="/system", tags=["System"])


# ===== SystemSetting =====
@router.post("/settings", response_model=SystemSettingResponse, status_code=status.HTTP_201_CREATED)
def create_setting(payload: SystemSettingCreate, db: Session = Depends(get_db)):
    return crud.create_setting(db, payload.dict())

@router.get("/settings", response_model=list[SystemSettingResponse])
def list_settings(
    offset: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=100),
    db: Session = Depends(get_db),
):
    return crud.list_settings(db, offset=offset, limit=limit)


@router.get("/settings/current", response_model=SystemSettingResponse)
def get_current_setting(db: Session = Depends(get_db)):
    obj = crud.get_current_setting(db)
    if not obj:
        raise HTTPException(status_code=404, detail="not found")
    return obj





@router.get("/settings/{setting_id}", response_model=SystemSettingResponse)
def get_setting(setting_id: int, db: Session = Depends(get_db)):
    obj = crud.get_setting(db, setting_id)
    if not obj:
        raise HTTPException(status_code=404, detail="not found")
    return obj


@router.patch("/settings/{setting_id}", response_model=SystemSettingResponse)
def update_setting(setting_id: int, payload: SystemSettingUpdate, db: Session = Depends(get_db)):
    obj = crud.update_setting(db, setting_id, payload.dict(exclude_unset=True))
    if not obj:
        raise HTTPException(status_code=404, detail="not found")
    return obj


@router.delete("/settings/{setting_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_setting(setting_id: int, db: Session = Depends(get_db)):
    if not crud.delete_setting(db, setting_id):
        raise HTTPException(status_code=404, detail="not found")
    return None


# ===== QuickCategory =====
@router.get("/settings/{setting_id}/quick-categories", response_model=list[QuickCategoryResponse])
def list_quick_categories(
    setting_id: int,
    offset: int = Query(0, ge=0),
    limit: int = Query(200, ge=1, le=1000),
    db: Session = Depends(get_db),
):
    if not crud.get_setting(db, setting_id):
        raise HTTPException(status_code=404, detail="setting not found")
    return crud.list_quick_categories(db, setting_id, offset=offset, limit=limit)


@router.post(
    "/settings/{setting_id}/quick-categories",
    response_model=QuickCategoryResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_quick_category(setting_id: int, payload: QuickCategoryCreate, db: Session = Depends(get_db)):
    if not crud.get_setting(db, setting_id):
        raise HTTPException(status_code=404, detail="setting not found")
    data = payload.dict()
    data["setting_id"] = setting_id  # 강제 일치
    return crud.create_quick_category(db, data)


@router.get("/quick-categories/{qc_id}", response_model=QuickCategoryResponse)
def get_quick_category(qc_id: int, db: Session = Depends(get_db)):
    obj = crud.get_quick_category(db, qc_id)
    if not obj:
        raise HTTPException(status_code=404, detail="not found")
    return obj


@router.patch("/quick-categories/{qc_id}", response_model=QuickCategoryResponse)
def update_quick_category(qc_id: int, payload: QuickCategoryUpdate, db: Session = Depends(get_db)):
    obj = crud.update_quick_category(db, qc_id, payload.dict(exclude_unset=True))
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


@router.post("/settings/{setting_id}/quick-categories/reorder")
def reorder_quick_categories(setting_id: int, payload: ReorderIn, db: Session = Depends(get_db)):
    if not crud.get_setting(db, setting_id):
        raise HTTPException(status_code=404, detail="setting not found")
    n = crud.reorder_quick_categories(db, setting_id, payload.ordered_ids)
    return {"updated": n}


@router.post("/settings/{setting_id}/quick-categories/normalize")
def normalize_quick_category_order(setting_id: int, db: Session = Depends(get_db)):
    if not crud.get_setting(db, setting_id):
        raise HTTPException(status_code=404, detail="setting not found")
    n = crud.normalize_quick_category_order(db, setting_id)
    return {"normalized": n}
