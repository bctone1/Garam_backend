from typing import Optional, List
from sqlalchemy import select, update as sa_update, delete as sa_delete
from sqlalchemy.orm import Session
from models.admin_user import AdminUser
# crud/admin_user.py

# 기본 조회
def get(db: Session, user_id: int) -> Optional[AdminUser]:
    return db.get(AdminUser, user_id)


def get_by_email(db: Session, email: str) -> Optional[AdminUser]:
    return db.execute(
        select(AdminUser).where(AdminUser.email == email)
    ).scalar_one_or_none()


# 리스트 조회 (간단 필터)
def list_users(
    db: Session,
    offset: int = 0,
    limit: int = 50,
    department: Optional[str] = None,
    search: Optional[str] = None,  # name/email 부분검색
) -> List[AdminUser]:
    stmt = select(AdminUser).order_by(AdminUser.id.asc())

    if department:
        stmt = stmt.where(AdminUser.department == department)

    if search:
        like = f"%{search}%"
        stmt = stmt.where((AdminUser.name.ilike(like)) | (AdminUser.email.ilike(like)))

    stmt = stmt.offset(offset).limit(min(limit, 100))
    return db.execute(stmt).scalars().all()


# 생성
def create(db: Session, data: dict) -> AdminUser:
    obj = AdminUser(**data)
    db.add(obj)
    db.commit()
    db.refresh(obj)
    return obj


# 수정 (부분 업데이트)
def update(db: Session, user_id: int, data: dict) -> Optional[AdminUser]:
    obj = get(db, user_id)
    if not obj:
        return None

    for k, v in data.items():
        setattr(obj, k, v)

    db.add(obj)
    db.commit()
    db.refresh(obj)
    return obj


# 삭제
def delete(db: Session, user_id: int) -> bool:
    obj = get(db, user_id)
    if not obj:
        return False
    db.delete(obj)
    db.commit()
    return True

