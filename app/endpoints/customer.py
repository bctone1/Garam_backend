# app/endpoints/customer.py
from __future__ import annotations

import csv
import io
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, File, UploadFile, status
from sqlalchemy.orm import Session

from database.session import get_db
from crud import customer as crud
from schemas.customer import CustomerResponse, CustomerCreate, CustomerUpdate, CsvUploadResponse

router = APIRouter(prefix="/customer", tags=["Customer"])

# CSV 컬럼 매핑 (한글 → 영문 필드)
_CSV_COL_MAP = {
    "사업자번호": "business_number",
    "상호명": "business_name",
    "전화번호": "phone",
    "주소": "address",
}


@router.post("/", response_model=CustomerResponse, status_code=status.HTTP_201_CREATED)
def create_customer(
    payload: CustomerCreate,
    db: Session = Depends(get_db),
):
    return crud.create(db, payload.model_dump())


@router.post("/upload_csv", response_model=CsvUploadResponse)
def upload_csv(
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
):
    content = file.file.read().decode("utf-8-sig")
    reader = csv.DictReader(io.StringIO(content))

    rows: list[dict] = []
    for line in reader:
        mapped = {
            _CSV_COL_MAP.get(k, k): (v.strip() if v else v)
            for k, v in line.items()
        }
        if not mapped.get("business_name"):
            continue
        rows.append(mapped)

    created = crud.bulk_create_from_csv(db, rows)
    return {"total": len(rows), "created": len(created)}


@router.get("/", response_model=list[CustomerResponse])
def list_customers(
    offset: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=100),
    db: Session = Depends(get_db),
):
    return crud.list_customers(db, offset=offset, limit=limit)


@router.get("/{customer_id}", response_model=CustomerResponse)
def get_customer(customer_id: int, db: Session = Depends(get_db)):
    obj = crud.get(db, customer_id)
    if not obj:
        raise HTTPException(status_code=404, detail="not found")
    return obj


@router.patch("/{customer_id}", response_model=CustomerResponse)
def update_customer(
    customer_id: int,
    payload: CustomerUpdate,
    db: Session = Depends(get_db),
):
    obj = crud.update(db, customer_id, payload.model_dump(exclude_unset=True))
    if not obj:
        raise HTTPException(status_code=404, detail="not found")
    return obj


@router.delete("/{customer_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_customer(customer_id: int, db: Session = Depends(get_db)):
    if not crud.delete(db, customer_id):
        raise HTTPException(status_code=404, detail="not found")
    return None
