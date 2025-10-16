from pydantic import BaseModel, EmailStr
from datetime import datetime

# 공통 필드
class AdminUserBase(BaseModel):
    name: str
    email: EmailStr
    department: str
    password:str

# 생성 시 입력
class AdminUserCreate(AdminUserBase):
    pass

# 수정 시 입력 (부분 업데이트 가능)
class AdminUserUpdate(BaseModel):
    name: str | None = None
    department: str | None = None

# 응답 스키마
class AdminUserResponse(AdminUserBase):
    id: int
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True
