# DB 접근 로직

from __future__ import annotations
from typing import Optional, List, Dict, Any, Literal, Sequence
from sqlalchemy import select, and_, func
from sqlalchemy.orm import Session
from models.knowledge import Knowledge, KnowledgePage, KnowledgeChunk
from typing import Iterable
KStatus = Literal["active", "processing", "error"]
VectorArray = Sequence[float]


# =========================
# Knowledge
# =========================
def get_knowledge(db: Session, knowledge_id: int) -> Optional[Knowledge]:
    return db.get(Knowledge, knowledge_id)


def list_knowledge(
    db: Session,
    *,
    offset: int = 0,
    limit: int = 50,
    status: Optional[KStatus] = None,
    q: Optional[str] = None,  # original_name / preview 검색
) -> List[Knowledge]:
    stmt = select(Knowledge)
    if status:
        stmt = stmt.where(Knowledge.status == status)
    if q:
        like = f"%{q}%"
        stmt = stmt.where(Knowledge.original_name.ilike(like) | Knowledge.preview.ilike(like))
    stmt = stmt.order_by(Knowledge.created_at.desc()).offset(offset).limit(min(limit, 100))
    return db.execute(stmt).scalars().all()


def create_knowledge(db: Session, data: dict) -> Knowledge:
    obj = Knowledge(**data)
    db.add(obj)
    db.commit()
    db.refresh(obj)
    return obj


def update_knowledge(db: Session, knowledge_id: int, data: Dict[str, Any]) -> Optional[Knowledge]:
    obj = get_knowledge(db, knowledge_id)
    if not obj:
        return None
    for k, v in data.items():
        setattr(obj, k, v)
    db.add(obj)
    db.commit()
    db.refresh(obj)
    return obj


def delete_knowledge(db: Session, knowledge_id: int) -> bool:
    obj = get_knowledge(db, knowledge_id)
    if not obj:
        return False
    db.delete(obj)  # pages, chunks는 CASCADE/관계로 정리
    db.commit()
    return True


# =========================
# KnowledgePage
# =========================
def get_page(db: Session, page_id: int) -> Optional[KnowledgePage]:
    return db.get(KnowledgePage, page_id)


def get_page_by_doc_page(db: Session, knowledge_id: int, page_no: int) -> Optional[KnowledgePage]:
    stmt = select(KnowledgePage).where(
        KnowledgePage.knowledge_id == knowledge_id, KnowledgePage.page_no == page_no
    )
    return db.execute(stmt).scalar_one_or_none()


def list_pages(
    db: Session, knowledge_id: int, *, offset: int = 0, limit: int = 500
) -> List[KnowledgePage]:
    stmt = (
        select(KnowledgePage)
        .where(KnowledgePage.knowledge_id == knowledge_id)
        .order_by(KnowledgePage.page_no.asc())
        .offset(offset)
        .limit(min(limit, 2000))
    )
    return db.execute(stmt).scalars().all()


def upsert_page(
    db: Session, *, knowledge_id: int, page_no: int, image_url: str
) -> KnowledgePage:
    obj = get_page_by_doc_page(db, knowledge_id, page_no)
    if obj:
        obj.image_url = image_url
        db.add(obj)
        db.commit()
        db.refresh(obj)
        return obj
    obj = KnowledgePage(knowledge_id=knowledge_id, page_no=page_no, image_url=image_url)
    db.add(obj)
    db.commit()
    db.refresh(obj)
    return obj


def bulk_create_pages(db, knowledge_id: int, pages: list[dict]) -> int:
    objs = [
        KnowledgePage(
            knowledge_id=knowledge_id,
            page_no=p["page_no"],
            image_url=(p.get("image_url") or ""),  # None 방지
        )
        for p in pages
    ]
    db.add_all(objs)
    db.commit()
    return len(objs)


def delete_page(db: Session, page_id: int) -> bool:
    obj = get_page(db, page_id)
    if not obj:
        return False
    db.delete(obj)  # 관련 chunk는 ondelete=SET NULL
    db.commit()
    return True


# =========================
# KnowledgeChunk
# =========================
def get_chunk(db: Session, chunk_id: int) -> Optional[KnowledgeChunk]:
    return db.get(KnowledgeChunk, chunk_id)


def get_chunk_by_doc_index(db: Session, knowledge_id: int, chunk_index: int) -> Optional[KnowledgeChunk]:
    stmt = select(KnowledgeChunk).where(
        KnowledgeChunk.knowledge_id == knowledge_id,
        KnowledgeChunk.chunk_index == chunk_index,
    )
    return db.execute(stmt).scalar_one_or_none()


def list_chunks(
    db: Session,
    *,
    knowledge_id: int,
    page_id: Optional[int] = None,
    offset: int = 0,
    limit: int = 1000,
    order_by_index: bool = True,
) -> List[KnowledgeChunk]:
    stmt = select(KnowledgeChunk).where(KnowledgeChunk.knowledge_id == knowledge_id)
    if page_id is not None:
        stmt = stmt.where(KnowledgeChunk.page_id == page_id)
    stmt = stmt.order_by(KnowledgeChunk.chunk_index.asc() if order_by_index else KnowledgeChunk.created_at.asc())
    stmt = stmt.offset(offset).limit(min(limit, 5000))
    return db.execute(stmt).scalars().all()


def create_chunk(
    db: Session,
    *,
    knowledge_id: int,
    page_id: Optional[int],
    chunk_index: int,
    chunk_text: str,
    vector_memory: VectorArray,
) -> KnowledgeChunk:
    obj = KnowledgeChunk(
        knowledge_id=knowledge_id,
        page_id=page_id,
        chunk_index=chunk_index,
        chunk_text=chunk_text,
        vector_memory=vector_memory,
    )
    db.add(obj)
    db.commit()
    db.refresh(obj)
    return obj


def create_knowledge_chunks(db, knowledge_id: int, chunks: list[str], vectors: list[list[float]]):
    """chunks+vectors 배치를 1부터 인덱싱해 저장"""
    items = [
        {
            "page_id": None,
            "chunk_index": i,              # 1부터
            "chunk_text": text,
            "vector_memory": vec,
        }
        for i, (text, vec) in enumerate(zip(chunks, vectors), start=1)
        if text and vec is not None
    ]
    return bulk_upsert_chunks(db, knowledge_id, items)


def upsert_chunk(
    db: Session,
    *,
    knowledge_id: int,
    page_id: Optional[int],
    chunk_index: int,
    chunk_text: str,
    vector_memory: VectorArray,
) -> KnowledgeChunk:
    obj = get_chunk_by_doc_index(db, knowledge_id, chunk_index)
    if obj:
        obj.page_id = page_id
        obj.chunk_text = chunk_text
        obj.vector_memory = vector_memory
        db.add(obj)
        db.commit()
        db.refresh(obj)
        return obj
    return create_chunk(
        db,
        knowledge_id=knowledge_id,
        page_id=page_id,
        chunk_index=chunk_index,
        chunk_text=chunk_text,
        vector_memory=vector_memory,
    )


def bulk_upsert_chunks(
    db: Session, knowledge_id: int, items: List[Dict[str, Any]]
) -> List[KnowledgeChunk]:
    """
    items: [{page_id?, chunk_index, chunk_text, vector_memory}, ...]
    """
    out: List[KnowledgeChunk] = []
    # 미리 존재 인덱스 조회
    existing = db.execute(
        select(KnowledgeChunk.chunk_index, KnowledgeChunk.id).where(KnowledgeChunk.knowledge_id == knowledge_id)
    ).all()
    idx_to_id = {row[0]: row[1] for row in existing}

    for it in items:
        idx = int(it["chunk_index"])
        if idx in idx_to_id:
            obj = db.get(KnowledgeChunk, idx_to_id[idx])
            obj.page_id = it.get("page_id")
            obj.chunk_text = it["chunk_text"]
            obj.vector_memory = it["vector_memory"]
            db.add(obj)
            out.append(obj)
        else:
            obj = KnowledgeChunk(
                knowledge_id=knowledge_id,
                page_id=it.get("page_id"),
                chunk_index=idx,
                chunk_text=it["chunk_text"],
                vector_memory=it["vector_memory"],
            )
            db.add(obj)
            out.append(obj)

    db.commit()
    for o in out:
        db.refresh(o)
    return out


def delete_chunk(db: Session, chunk_id: int) -> bool:
    obj = get_chunk(db, chunk_id)
    if not obj:
        return False
    db.delete(obj)
    db.commit()
    return True


def delete_chunks_by_knowledge(db: Session, knowledge_id: int) -> int:
    rows = list_chunks(db, knowledge_id=knowledge_id, limit=10_000)
    for r in rows:
        db.delete(r)
    db.commit()
    return len(rows)


# =========================
# Vector search (pgvector)
# =========================
def search_chunks_by_vector(
    db: Session,
    *,
    query_vector: VectorArray,
    knowledge_id: Optional[int] = None,
    top_k: int = 5,
) -> List[KnowledgeChunk]:
    """
    cosine distance 기준 최근접 검색.
    pgvector.sqlalchemy의 comparator 사용: column.cosine_distance(vec)
    """
    stmt = select(KnowledgeChunk)
    if knowledge_id is not None:
        stmt = stmt.where(KnowledgeChunk.knowledge_id == knowledge_id)
    stmt = stmt.order_by(KnowledgeChunk.vector_memory.cosine_distance(query_vector)).limit(min(top_k, 200))
    return db.execute(stmt).scalars().all()


# =========================
# Simple stats
# =========================
def knowledge_stats(db: Session, knowledge_id: int) -> Dict[str, Any]:
    pages = db.execute(
        select(func.count()).select_from(KnowledgePage).where(KnowledgePage.knowledge_id == knowledge_id)
    ).scalar_one()
    chunks = db.execute(
        select(func.count()).select_from(KnowledgeChunk).where(KnowledgeChunk.knowledge_id == knowledge_id)
    ).scalar_one()
    return {"pages": int(pages or 0), "chunks": int(chunks or 0)}
