# Pydantic 스키마 (요청/응답)

from pydantic import BaseModel, Field
from datetime import datetime
from typing import Optional, Literal, List


# ===============================
# Knowledge
# ===============================
KnowledgeStatus = Literal["active", "processing", "error"]

class KnowledgeBase(BaseModel):
    original_name: str
    type: str                     # MIME type
    size: int = Field(ge=0)
    status: KnowledgeStatus
    preview: str                  # 짧은 요약문

# 업로드는 FastAPI File(...)받고 여기는 메타 데이터만 받음
class KnowledgeCreate(BaseModel):
    original_name: str
    type: str
    size: int
    status: str = "uploaded"
    preview: str = ""


class KnowledgeUpdate(BaseModel):
    original_name: Optional[str] = None
    type: Optional[str] = None
    size: Optional[int] = Field(default=None, ge=0)
    status: Optional[KnowledgeStatus] = None
    preview: Optional[str] = None


class KnowledgeResponse(KnowledgeBase):
    id: int
    created_at: datetime

    class Config:
        from_attributes = True


# ===============================
# KnowledgePage
# ===============================
class KnowledgePageBase(BaseModel):
    knowledge_id: int
    page_no: int = Field(ge=1)
    image_url: str


class KnowledgePageCreate(KnowledgePageBase):
    pass


class KnowledgePageUpdate(BaseModel):
    page_no: Optional[int] = Field(default=None, ge=1)
    image_url: Optional[str] = None


class KnowledgePageResponse(KnowledgePageBase):
    id: int
    created_at: datetime

    class Config:
        from_attributes = True


# ===============================
# KnowledgeChunk
# ===============================
class KnowledgeChunkBase(BaseModel):
    knowledge_id: int
    page_id: Optional[int] = None
    chunk_index: int = Field(ge=1)
    chunk_text: str
    # vector_memory는 내부 계산/저장용. API 입력으로 받지 않는 것이 기본.
    # 필요 시 아래 주석 해제 후 list[float]로 받도록 변경.
    # vector_memory: List[float]


class KnowledgeChunkCreate(KnowledgeChunkBase):
    pass


class KnowledgeChunkUpdate(BaseModel):
    page_id: Optional[int] = None
    chunk_index: Optional[int] = Field(default=None, ge=1)
    chunk_text: Optional[str] = None
    # vector_memory: Optional[List[float]] = None


class KnowledgeChunkResponse(KnowledgeChunkBase):
    id: int
    created_at: datetime

    class Config:
        from_attributes = True
