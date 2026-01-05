# app/endpoints/admin_user.py
from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session
from database.session import get_db
from crud import admin_user as crud
from schemas.admin_user import AdminUserCreate, AdminUserUpdate, AdminUserResponse

router = APIRouter(prefix="/admin_users", tags=["Admin User"])

@router.post("/", response_model=AdminUserResponse, status_code=status.HTTP_201_CREATED)
def create_user(payload: AdminUserCreate, db: Session = Depends(get_db)):
    if crud.get_by_email(db, payload.email):
        raise HTTPException(status_code=409, detail="email already exists")
    return crud.create(db, payload.model_dump())

@router.get("/", response_model=list[AdminUserResponse])
def list_users(
    offset: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=100),
    department: str | None = Query(None),
        db: Session = Depends(get_db),
):
        return crud.list_users(db, offset=offset, limit=limit, department=department)


@router.get("/{user_id}", response_model=AdminUserResponse)
def get_user(user_id: int, db: Session = Depends(get_db)):
    obj = crud.get(db, user_id)
    if not obj:
        raise HTTPException(status_code=404, detail="not found")
    return obj


@router.patch("/{user_id}", response_model=AdminUserResponse)
def update_user(user_id: int, payload: AdminUserUpdate, db: Session = Depends(get_db)):
    obj = crud.update(db, user_id, payload.model_dump(exclude_unset=True))
    if not obj:
        raise HTTPException(status_code=404, detail="not found")
    return obj


@router.delete("/{user_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_user(user_id: int, db: Session = Depends(get_db)):
    if not crud.delete(db, user_id):
        raise HTTPException(status_code=404, detail="not found")
    return None
