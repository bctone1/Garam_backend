# app/endpoints/knowledge.py
from __future__ import annotations
from typing import Optional, List, Literal
from fastapi import APIRouter, Depends, HTTPException, Query, status, UploadFile, File
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from database.session import get_db
from crud import knowledge as crud
from schemas.knowledge import (
    KnowledgeCreate, KnowledgeUpdate, KnowledgeResponse,
    KnowledgePageCreate, KnowledgePageResponse,   # 사용 안 하는 KnowledgePageUpdate 제거
    KnowledgeChunkResponse)

from service.upload_pipeline import UploadPipeline

router = APIRouter(prefix="/knowledge", tags=["Knowledge"])
KStatus = Literal["active", "processing", "error"]
# VECTOR_DIM = 1536  # 기본 벡터 보정은 CRUD 래퍼로 위임하므로 제거

# ---------- Knowledge ----------

@router.post("/", response_model=KnowledgeResponse, status_code=status.HTTP_201_CREATED)
def create_knowledge(db: Session = Depends(get_db), file: UploadFile = File(...)):
    data = KnowledgeCreate(
        original_name=file.filename,
        type=file.content_type,
        size=len(file.file.read()),  # 파일 크기 직접 계산
        status="active",    # 'active' | 'processing' | 'error'
        preview=""
    )
    file.file.seek(0)  # size 측정 후 포인터 원복
    return crud.create_knowledge(db, data.model_dump())

@router.get("/", response_model=list[KnowledgeResponse])
def list_knowledge(
    offset: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=100),
    status: Optional[KStatus] = Query(None),
    q: Optional[str] = Query(None, description="search in original_name/preview"),
    db: Session = Depends(get_db),
):
    return crud.list_knowledge(db, offset=offset, limit=limit, status=status, q=q)  # type: ignore[arg-type]


@router.get("/{knowledge_id}", response_model=KnowledgeResponse)
def get_knowledge(knowledge_id: int, db: Session = Depends(get_db)):
    obj = crud.get_knowledge(db, knowledge_id)
    if not obj:
        raise HTTPException(status_code=404, detail="not found")
    return obj


@router.patch("/{knowledge_id}", response_model=KnowledgeResponse)
def update_knowledge(knowledge_id: int, payload: KnowledgeUpdate, db: Session = Depends(get_db)):
    obj = crud.update_knowledge(db, knowledge_id, payload.model_dump(exclude_unset=True))
    if not obj:
        raise HTTPException(status_code=404, detail="not found")
    return obj


@router.delete("/{knowledge_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_knowledge(knowledge_id: int, db: Session = Depends(get_db)):
    if not crud.delete_knowledge(db, knowledge_id):
        raise HTTPException(status_code=404, detail="not found")
    return None


@router.get("/{knowledge_id}/stats")
def knowledge_stats(knowledge_id: int, db: Session = Depends(get_db)):
    if not crud.get_knowledge(db, knowledge_id):
        raise HTTPException(status_code=404, detail="not found")
    return crud.knowledge_stats(db, knowledge_id)


# ---------- KnowledgePage ----------
class PageUpsertIn(BaseModel):
    image_url: str


@router.get("/{knowledge_id}/pages", response_model=list[KnowledgePageResponse])
def list_pages(
    knowledge_id: int,
    offset: int = Query(0, ge=0),
    limit: int = Query(500, ge=1, le=2000),
    db: Session = Depends(get_db),
):
    if not crud.get_knowledge(db, knowledge_id):
        raise HTTPException(status_code=404, detail="knowledge not found")
    return crud.list_pages(db, knowledge_id, offset=offset, limit=limit)


@router.put("/{knowledge_id}/pages/{page_no}", response_model=KnowledgePageResponse)
def upsert_page(knowledge_id: int, page_no: int, payload: PageUpsertIn, db: Session = Depends(get_db)):
    if not crud.get_knowledge(db, knowledge_id):
        raise HTTPException(status_code=404, detail="knowledge not found")
    return crud.upsert_page(db, knowledge_id=knowledge_id, page_no=page_no, image_url=payload.image_url)


@router.get("/pages/{page_id}", response_model=KnowledgePageResponse)
def get_page(page_id: int, db: Session = Depends(get_db)):
    obj = crud.get_page(db, page_id)
    if not obj:
        raise HTTPException(status_code=404, detail="not found")
    return obj


@router.delete("/pages/{page_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_page(page_id: int, db: Session = Depends(get_db)):
    if not crud.delete_page(db, page_id):
        raise HTTPException(status_code=404, detail="not found")
    return None


class PagesBulkCreateIn(BaseModel):
    pages: list[KnowledgePageCreate]


@router.post("/{knowledge_id}/pages/bulk", response_model=list[KnowledgePageResponse], status_code=status.HTTP_201_CREATED)
def bulk_create_pages(knowledge_id: int, payload: PagesBulkCreateIn, db: Session = Depends(get_db)):
    if not crud.get_knowledge(db, knowledge_id):
        raise HTTPException(status_code=404, detail="knowledge not found")
    # 안전을 위해 knowledge_id 강제 주입
    items = [{**p.model_dump(), "knowledge_id": knowledge_id} for p in payload.pages]
    return crud.bulk_create_pages_any(db, items)  # ← 변경: 리턴 타입 정합성 맞는 CRUD 래퍼 사용


# ---------- KnowledgeChunk ----------
class ChunkCreateIn(BaseModel):
    page_id: Optional[int] = None
    chunk_index: int = Field(..., ge=1)
    chunk_text: str
    vector_memory: Optional[List[float]] = Field(default=None, description="1536-dim vector")


class ChunkUpsertIn(ChunkCreateIn):
    pass


class ChunksBulkUpsertIn(BaseModel):
    items: list[ChunkCreateIn]


@router.get("/{knowledge_id}/chunks", response_model=list[KnowledgeChunkResponse])
def list_chunks(
    knowledge_id: int,
    page_id: Optional[int] = Query(None),
    offset: int = Query(0, ge=0),
    limit: int = Query(1000, ge=1, le=5000),
    order_by_index: bool = Query(True),
    db: Session = Depends(get_db),
):
    if not crud.get_knowledge(db, knowledge_id):
        raise HTTPException(status_code=404, detail="knowledge not found")
    return crud.list_chunks(
        db,
        knowledge_id=knowledge_id,
        page_id=page_id,
        offset=offset,
        limit=limit,
        order_by_index=order_by_index,
    )


@router.post("/{knowledge_id}/chunks", response_model=KnowledgeChunkResponse, status_code=status.HTTP_201_CREATED)
def create_chunk(knowledge_id: int, payload: ChunkCreateIn, db: Session = Depends(get_db)):
    if not crud.get_knowledge(db, knowledge_id):
        raise HTTPException(status_code=404, detail="knowledge not found")
    return crud.create_chunk_with_default_vector(  # ← 변경: 기본 벡터 보정은 CRUD 래퍼로 위임
        db,
        knowledge_id=knowledge_id,
        page_id=payload.page_id,
        chunk_index=payload.chunk_index,
        chunk_text=payload.chunk_text,
        vector_memory=payload.vector_memory,
    )


@router.put("/{knowledge_id}/chunks", response_model=KnowledgeChunkResponse)
def upsert_chunk(knowledge_id: int, payload: ChunkUpsertIn, db: Session = Depends(get_db)):
    if not crud.get_knowledge(db, knowledge_id):
        raise HTTPException(status_code=404, detail="knowledge not found")
    return crud.upsert_chunk_with_default_vector(  # ← 변경
        db,
        knowledge_id=knowledge_id,
        page_id=payload.page_id,
        chunk_index=payload.chunk_index,
        chunk_text=payload.chunk_text,
        vector_memory=payload.vector_memory,
    )


@router.post("/{knowledge_id}/chunks/bulk", response_model=list[KnowledgeChunkResponse], status_code=status.HTTP_201_CREATED)
def bulk_upsert_chunks(knowledge_id: int, payload: ChunksBulkUpsertIn, db: Session = Depends(get_db)):
    if not crud.get_knowledge(db, knowledge_id):
        raise HTTPException(status_code=404, detail="knowledge not found")
    raw_items = [
        {
            "page_id": it.page_id,
            "chunk_index": it.chunk_index,
            "chunk_text": it.chunk_text,
            "vector_memory": it.vector_memory,  # None → CRUD 래퍼에서 0.0 * 1536 보정
        }
        for it in payload.items
    ]
    return crud.bulk_upsert_chunks_with_default(db, knowledge_id, raw_items)  # ← 변경


@router.get("/chunks/{chunk_id}", response_model=KnowledgeChunkResponse)
def get_chunk(chunk_id: int, db: Session = Depends(get_db)):
    obj = crud.get_chunk(db, chunk_id)
    if not obj:
        raise HTTPException(status_code=404, detail="not found")
    return obj


@router.delete("/chunks/{chunk_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_chunk(chunk_id: int, db: Session = Depends(get_db)):
    if not crud.delete_chunk(db, chunk_id):
        raise HTTPException(status_code=404, detail="not found")
    return None


@router.delete("/{knowledge_id}/chunks", status_code=status.HTTP_200_OK)
def delete_chunks_by_knowledge(knowledge_id: int, db: Session = Depends(get_db)):
    if not crud.get_knowledge(db, knowledge_id):
        raise HTTPException(status_code=404, detail="knowledge not found")
    n = crud.delete_chunks_by_knowledge(db, knowledge_id)
    return {"deleted": n}


# ---------- Vector search ----------
class VectorSearchIn(BaseModel):
    query_vector: List[float]
    knowledge_id: Optional[int] = None
    top_k: int = Field(5, ge=1, le=200)


@router.post("/chunks/search", response_model=list[KnowledgeChunkResponse])
def search_chunks(payload: VectorSearchIn, db: Session = Depends(get_db)):
    return crud.search_chunks_by_vector(
        db,
        query_vector=payload.query_vector,
        knowledge_id=payload.knowledge_id,
        top_k=payload.top_k,
    )

@router.post("/upload", response_model=KnowledgeResponse)
def upload_knowledge(
        db: Session = Depends(get_db),
        file: UploadFile = File(...)):
    pipeline = UploadPipeline(db, user_id="TSET_USER")    ## 추후에 user_id: str = Depends(get_current_user_id)로 변경
    return pipeline.run(file)
