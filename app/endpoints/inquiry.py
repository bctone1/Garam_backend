# app/routers/inquiries.py
from __future__ import annotations
from typing import Optional
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session, joinedload

from database.session import get_db
from crud import inquiry as crud
from crud.inquiry import serialize_inquiry
from models.inquiry import Inquiry
from schemas.inquiry import (
    InquiryCreate, InquiryUpdate, InquiryResponse, InquiryHistoryResponse,
    AssignIn, UnassignIn, TransferIn, SetStatusIn, SatisfactionIn, HistoryNoteIn
)

router = APIRouter(prefix="/inquiries", tags=["Inquiry"])

# -------- 전체 조회 (관리자용) --------
@router.get("/get_inquiry_list")
def get_inquiry_list(db: Session = Depends(get_db)):
    inquiries = (
        db.query(Inquiry)
        .options(
            joinedload(Inquiry.assignee),
            joinedload(Inquiry.histories),
        )
        .order_by(Inquiry.id.desc())
        .all()
    )
    return [serialize_inquiry(i) for i in inquiries]


# -------- CRUD --------
@router.post("/", response_model=InquiryResponse, status_code=status.HTTP_201_CREATED)
def create_inquiry(payload: InquiryCreate, db: Session = Depends(get_db)):
    return crud.create(db, payload.model_dump(exclude_unset=True))


@router.get("/", response_model=list[InquiryResponse])
def list_inquiries(
    offset: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=100),
    status: Optional[str] = Query(None),
    assignee_admin_id: Optional[int] = Query(None),
    q: Optional[str] = Query(None, description="search in name/company/phone/content"),
    created_from: Optional[datetime] = Query(None),
    created_to: Optional[datetime] = Query(None),
    db: Session = Depends(get_db),
):
    return crud.list_inquiries(
        db,
        offset=offset,
        limit=limit,
        status=status,  # type: ignore[arg-type]
        assignee_admin_id=assignee_admin_id,
        q=q,
        created_from=created_from,
        created_to=created_to,
    )


@router.get("/{inquiry_id}", response_model=InquiryResponse)
def get_inquiry(inquiry_id: int, db: Session = Depends(get_db)):
    obj = crud.get(db, inquiry_id)
    if not obj:
        raise HTTPException(status_code=404, detail="not found")
    return obj


@router.patch("/{inquiry_id}", response_model=InquiryResponse)
def update_inquiry(inquiry_id: int, payload: InquiryUpdate, db: Session = Depends(get_db)):
    obj = crud.update(db, inquiry_id, payload.model_dump(exclude_unset=True))
    if not obj:
        raise HTTPException(status_code=404, detail="not found")
    return obj


@router.delete("/{inquiry_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_inquiry(inquiry_id: int, db: Session = Depends(get_db)):
    if not crud.delete(db, inquiry_id):
        raise HTTPException(status_code=404, detail="not found")
    return None


# -------- 업무 흐름 (assign / unassign / transfer / status / satisfaction) --------
@router.post("/{inquiry_id}/assign", response_model=InquiryResponse)
def assign(inquiry_id: int, payload: AssignIn, db: Session = Depends(get_db)):
    obj = crud.assign(db, inquiry_id, payload.admin_id, actor_admin_id=payload.actor_admin_id)
    if not obj:
        raise HTTPException(status_code=404, detail="not found")
    return obj


@router.post("/{inquiry_id}/unassign", response_model=InquiryResponse)
def unassign(inquiry_id: int, payload: UnassignIn | None = None, db: Session = Depends(get_db)):
    obj = crud.unassign(db, inquiry_id, actor_admin_id=(payload.actor_admin_id if payload else None))
    if not obj:
        raise HTTPException(status_code=404, detail="not found")
    return obj


@router.post("/{inquiry_id}/transfer", response_model=InquiryResponse)
def transfer(inquiry_id: int, payload: TransferIn, db: Session = Depends(get_db)):
    obj = crud.transfer(db, inquiry_id, payload.to_admin_id, actor_admin_id=payload.actor_admin_id)
    if not obj:
        raise HTTPException(status_code=404, detail="not found")
    return obj


@router.post("/{inquiry_id}/status", response_model=InquiryResponse)
def set_status(inquiry_id: int, payload: SetStatusIn, db: Session = Depends(get_db)):
    obj = crud.set_status(
        db,
        inquiry_id,
        payload.status,  # type: ignore[arg-type]
        actor_admin_id=payload.actor_admin_id,
        details=payload.details,
    )
    if not obj:
        raise HTTPException(status_code=404, detail="not found")
    return obj


@router.post("/{inquiry_id}/satisfaction", response_model=InquiryResponse)
def set_satisfaction(inquiry_id: int, payload: SatisfactionIn, db: Session = Depends(get_db)):
    obj = crud.set_customer_satisfaction(db, inquiry_id, payload.satisfaction)  # type: ignore[arg-type]
    if not obj:
        raise HTTPException(status_code=404, detail="not found")
    return obj


# -------- 이력 --------
@router.get("/{inquiry_id}/histories", response_model=list[InquiryHistoryResponse])
def list_histories(
    inquiry_id: int,
    offset: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=500),
    db: Session = Depends(get_db),
):
    if not crud.get(db, inquiry_id):
        raise HTTPException(status_code=404, detail="inquiry not found")
    return crud.list_histories(db, inquiry_id, offset=offset, limit=limit)


@router.post("/{inquiry_id}/histories/note", response_model=InquiryHistoryResponse)
def add_history_note(inquiry_id: int, payload: HistoryNoteIn, db: Session = Depends(get_db)):
    if not crud.get(db, inquiry_id):
        raise HTTPException(status_code=404, detail="inquiry not found")
    return crud.add_history_note(
        db,
        inquiry_id,
        action=payload.action,
        admin_id=payload.admin_id,
        details=payload.details,
    )

