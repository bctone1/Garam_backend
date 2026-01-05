# app/endpoints/faq.py
from __future__ import annotations
from typing import Optional, Literal
from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from database.session import get_db
from crud import faq as crud
from schemas.faq import FAQCreate, FAQUpdate, FAQResponse

OrderBy = Literal["recent", "views", "satisfaction"]

router = APIRouter(prefix="/faqs", tags=["FAQ"])


@router.post("/", response_model=FAQResponse, status_code=status.HTTP_201_CREATED)
def create_faq(payload: FAQCreate, db: Session = Depends(get_db)):
    return crud.create(db, payload.dict(exclude_unset=True))


@router.get("/", response_model=list[FAQResponse])
def list_faqs(
    offset: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=100),
    q: Optional[str] = Query(None, description="search in question/answer"),
    order_by: OrderBy = Query("recent", pattern="^(recent|views|satisfaction)$"),
    quick_category_id: Optional[int] = Query(None, description="filter by quick_category_id"),
    include_category: bool = Query(False, description="load relationship (응답스키마는 동일)"),
    db: Session = Depends(get_db),
):
    return crud.list_faqs(
        db,
        offset=offset,
        limit=limit,
        q=q,
        order_by=order_by,
        quick_category_id=quick_category_id,
        include_category=include_category,
    )  # type: ignore[arg-type]


@router.get("/{faq_id}", response_model=FAQResponse)
def get_faq(
    faq_id: int,
    include_category: bool = Query(False, description="load relationship (응답스키마는 동일)"),
    db: Session = Depends(get_db),
):
    obj = crud.get(db, faq_id, include_category=include_category)
    if not obj:
        raise HTTPException(status_code=404, detail="not found")
    return obj


@router.patch("/{faq_id}", response_model=FAQResponse)
def update_faq(faq_id: int, payload: FAQUpdate, db: Session = Depends(get_db)):
    obj = crud.update(db, faq_id, payload.dict(exclude_unset=True))
    if not obj:
        raise HTTPException(status_code=404, detail="not found")
    return obj


@router.delete("/{faq_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_faq(faq_id: int, db: Session = Depends(get_db)):
    if not crud.delete(db, faq_id):
        raise HTTPException(status_code=404, detail="not found")
    return None


# ----- extra operations -----
@router.post("/{faq_id}/views", response_model=FAQResponse)
def increment_views(
    faq_id: int,
    delta: int = Query(1, ge=1, description="increment amount"),
    db: Session = Depends(get_db),
):
    obj = crud.increment_views(db, faq_id, delta=delta)
    if not obj:
        raise HTTPException(status_code=404, detail="not found")
    return obj


@router.put("/{faq_id}/satisfaction", response_model=FAQResponse)
def set_satisfaction_rate(
    faq_id: int,
    rate: float = Query(..., ge=0, le=100, description="0~100"),
    db: Session = Depends(get_db),
):
    obj = crud.set_satisfaction_rate(db, faq_id, rate=rate)
    if not obj:
        raise HTTPException(status_code=404, detail="not found")
    return obj
