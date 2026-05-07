# app/endpoints/notice.py
from __future__ import annotations
import os
import re
import shutil
from typing import Literal, Optional
from uuid import uuid4
from fastapi import APIRouter, Depends, HTTPException, Query, UploadFile, File, status
from sqlalchemy.orm import Session

from database.session import get_db
from crud import notice as crud
from schemas.notice import NoticeCreate, NoticeUpdate, NoticeResponse
from core.config import UPLOAD_FOLDER

router = APIRouter(prefix="/notices", tags=["Notice"])

NOTICE_IMAGE_DIR = os.path.join(UPLOAD_FOLDER, "uploads", "notice")
ALLOWED_IMAGE_TYPES = {"image/jpeg", "image/png", "image/gif", "image/webp"}


def _safe_filename(name: str) -> str:
    name = os.path.basename(name)
    name = re.sub(r"[^\w.\-]", "_", name)
    return name[:100] or "upload"

StatusFilter = Literal["all", "scheduled", "active", "expired"]


@router.post("/", response_model=NoticeResponse, status_code=status.HTTP_201_CREATED)
def create_notice(payload: NoticeCreate, db: Session = Depends(get_db)):
    return crud.create(db, payload.dict(exclude_unset=True))


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
    return obj


@router.delete("/{notice_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_notice(notice_id: int, db: Session = Depends(get_db)):
    if not crud.delete(db, notice_id):
        raise HTTPException(status_code=404, detail="not found")
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
