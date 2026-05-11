# app/endpoints/notice.py
from __future__ import annotations
import os
import re
import shutil
from datetime import datetime, timezone
from typing import Literal, Optional
from uuid import uuid4
from fastapi import APIRouter, Depends, HTTPException, Query, UploadFile, File, status
from sqlalchemy.orm import Session

from database.session import get_db
from crud import notice as crud
from schemas.notice import NoticeCreate, NoticeUpdate, NoticeResponse
from core.config import UPLOAD_FOLDER
from core.scheduler import schedule_notice_push, cancel_notice_push, push_notice_now

router = APIRouter(prefix="/notices", tags=["Notice"])

NOTICE_IMAGE_DIR = os.path.join(UPLOAD_FOLDER, "uploads", "notice")
ALLOWED_IMAGE_TYPES = {"image/jpeg", "image/png", "image/gif", "image/webp"}


def _safe_filename(name: str) -> str:
    name = os.path.basename(name)
    name = re.sub(r"[^\w.\-]", "_", name)
    return name[:100] or "upload"

StatusFilter = Literal["all", "scheduled", "active", "expired"]


def _maybe_schedule_push(notice) -> None:
    """공지의 is_important / start_at 상태에 따라 푸시 즉시 발송 또는 예약."""
    if not notice or not notice.is_important:
        return
    now = datetime.now(timezone.utc)
    start_at = notice.start_at
    end_at = notice.end_at
    # 이미 만료된 공지는 발송하지 않음
    if end_at and end_at <= now:
        return
    if not start_at or start_at <= now:
        push_notice_now(notice.id)
    else:
        schedule_notice_push(notice.id, start_at)


@router.post("/", response_model=NoticeResponse, status_code=status.HTTP_201_CREATED)
def create_notice(payload: NoticeCreate, db: Session = Depends(get_db)):
    obj = crud.create(db, payload.dict(exclude_unset=True))
    _maybe_schedule_push(obj)
    return obj


@router.get("/", response_model=list[NoticeResponse])
def list_notices(
    offset: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=100),
    status: StatusFilter = Query("all"),
    important_only: bool = Query(False),
    q: Optional[str] = Query(None),
    db: Session = Depends(get_db),
):
    return crud.list_notices(
        db,
        offset=offset,
        limit=limit,
        status=status,
        important_only=important_only,
        q=q,
    )


@router.get("/summary")
def notice_summary(db: Session = Depends(get_db)):
    return crud.count_by_status(db)


@router.get("/{notice_id}", response_model=NoticeResponse)
def get_notice(notice_id: int, db: Session = Depends(get_db)):
    obj = crud.get(db, notice_id)
    if not obj:
        raise HTTPException(status_code=404, detail="not found")
    return obj


@router.patch("/{notice_id}", response_model=NoticeResponse)
def update_notice(notice_id: int, payload: NoticeUpdate, db: Session = Depends(get_db)):
    obj = crud.update(db, notice_id, payload.dict(exclude_unset=True))
    if not obj:
        raise HTTPException(status_code=404, detail="not found")
    # 기존 예약 취소 후 새 상태에 맞춰 재스케줄
    cancel_notice_push(notice_id)
    _maybe_schedule_push(obj)
    return obj


@router.delete("/{notice_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_notice(notice_id: int, db: Session = Depends(get_db)):
    if not crud.delete(db, notice_id):
        raise HTTPException(status_code=404, detail="not found")
    cancel_notice_push(notice_id)
    return None


@router.post("/images", status_code=status.HTTP_201_CREATED)
def upload_notice_image(file: UploadFile = File(...)):
    if file.content_type not in ALLOWED_IMAGE_TYPES:
        raise HTTPException(status_code=400, detail="이미지 파일만 업로드 가능합니다 (jpeg/png/gif/webp)")

    os.makedirs(NOTICE_IMAGE_DIR, exist_ok=True)

    safe_name = _safe_filename(file.filename or "upload")
    filename = f"{uuid4().hex}_{safe_name}"
    save_path = os.path.join(NOTICE_IMAGE_DIR, filename)

    file.file.seek(0)
    with open(save_path, "wb") as out:
        shutil.copyfileobj(file.file, out, length=1024 * 1024)

    return {"url": f"/file/uploads/notice/{filename}"}
