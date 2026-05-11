# crud/knowledge.py
from __future__ import annotations

import logging
import os
from typing import Optional, List, Dict, Any, Literal, Sequence, Tuple

from sqlalchemy import select, func, or_
from sqlalchemy import text as sql_text
from sqlalchemy.orm import Session

from models.knowledge import Knowledge, KnowledgePage, KnowledgeChunk

KStatus = Literal["active", "processing", "error"]
VectorArray = Sequence[float]

log = logging.getLogger("knowledge")

# ivfflat 성능 튜닝(선택): 세션/트랜잭션 로컬로 probes 설정
# - 환경변수로 조절 가능: IVFFLAT_PROBES=10
_IVFFLAT_PROBES = int(os.getenv("IVFFLAT_PROBES", "10"))


# =========================================================
# Internal helpers
# =========================================================
def _maybe_set_ivfflat_probes(db: Session) -> None:
    """
    pgvector ivfflat 인덱스가 있는 경우 probes를 올려 recall을 조금 보강.
    - index가 없어도 SET LOCAL 자체는 보통 문제 없음
    - 혹시 DB 설정/버전에 따라 실패할 수 있으니 조용히 무시
    """
    try:
        p = max(1, min(int(_IVFFLAT_PROBES), 200))
        db.execute(sql_text("SET LOCAL ivfflat.probes = :p"), {"p": p})
    except Exception:
        return


def _finalize(db: Session, *, commit: bool) -> None:
    """
    commit=True: commit
    commit=False: flush (트랜잭션은 호출부가 commit/rollback)
    """
    if commit:
        db.commit()
    else:
        db.flush()


def _refresh_if_possible(db: Session, obj: Any, *, commit: bool) -> None:
    """
    commit=False여도 flush 이후 refresh는 가능(같은 트랜잭션 내).
    단, 대량 bulk에선 비용이 커서 필요한 곳만 씀.
    """
    try:
        db.refresh(obj)
    except Exception:
        # refresh 실패해도 핵심 로직은 돌아가게
        return


# =========================================================
# Internal helpers (search fallback)
# =========================================================
def _keyword_fallback_ilike(
    db: Session,
    *,
    knowledge_id: Optional[int],
    k: int,
    query_text: str,
    exclude_ids: Optional[set[int]] = None,
) -> List[KnowledgeChunk]:
    """
    키워드 폴백(확장/인덱스 없어도 동작)
    - ilike(%q%)
    - 공백 제거 매칭으로 "용지부족" vs "용지 부족" 같은 케이스 방어
    """
    qt = (query_text or "").strip()
    if not qt:
        return []

    like1 = f"%{qt[:200]}%"
    like2 = f"%{''.join(qt.split())[:200]}%"

    stmt = select(KnowledgeChunk)
    if knowledge_id is not None:
        stmt = stmt.where(KnowledgeChunk.knowledge_id == knowledge_id)

    stmt = (
        stmt.where(
            or_(
                KnowledgeChunk.chunk_text.ilike(like1),
                func.replace(KnowledgeChunk.chunk_text, " ", "").ilike(like2),
            )
        )
        .order_by(KnowledgeChunk.created_at.desc())
        .limit(min(max(int(k), 1) * 5, 200))
    )

    rows = db.execute(stmt).scalars().all()
    if exclude_ids:
        rows = [r for r in rows if getattr(r, "id", None) not in exclude_ids]
    return rows[: max(1, int(k))]


def _fallback_chunks(
    db: Session,
    *,
    knowledge_id: Optional[int],
    k: int,
    query_text: Optional[str] = None,
    exclude_ids: Optional[set[int]] = None,
) -> List[KnowledgeChunk]:
    # 1) 키워드 폴백 우선
    if query_text:
        rows = _keyword_fallback_ilike(
            db,
            knowledge_id=knowledge_id,
            k=k,
            query_text=query_text,
            exclude_ids=exclude_ids,
        )
        if rows:
            return rows

    # 2) 최후 폴백: 컨텍스트 비는 것 방지용으로 "앞쪽" 청크 반환
    if knowledge_id is not None:
        stmt = (
            select(KnowledgeChunk)
            .where(KnowledgeChunk.knowledge_id == knowledge_id)
            .order_by(KnowledgeChunk.chunk_index.asc())
            .limit(max(1, int(k)))
        )
    else:
        stmt = (
            select(KnowledgeChunk)
            .order_by(KnowledgeChunk.created_at.desc())
            .limit(max(1, int(k)))
        )

    rows = db.execute(stmt).scalars().all()
    if exclude_ids:
        rows = [r for r in rows if getattr(r, "id", None) not in exclude_ids]
    return rows[: max(1, int(k))]


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


def create_knowledge(db: Session, data: dict, commit: bool = True) -> Knowledge:
    obj = Knowledge(**data)
    db.add(obj)
    _finalize(db, commit=commit)
    _refresh_if_possible(db, obj, commit=commit)
    return obj


def update_knowledge(db: Session, knowledge_id: int, data: Dict[str, Any], commit: bool = True) -> Optional[Knowledge]:
    obj = get_knowledge(db, knowledge_id)
    if not obj:
        return None
    for k, v in data.items():
        setattr(obj, k, v)
    db.add(obj)
    _finalize(db, commit=commit)
    _refresh_if_possible(db, obj, commit=commit)
    return obj


def delete_knowledge(db: Session, knowledge_id: int, commit: bool = True) -> bool:
    obj = get_knowledge(db, knowledge_id)
    if not obj:
        return False
    db.delete(obj)  # pages, chunks는 CASCADE/관계로 정리
    _finalize(db, commit=commit)
    return True


# =========================
# KnowledgePage
# =========================
def get_page(db: Session, page_id: int) -> Optional[KnowledgePage]:
    return db.get(KnowledgePage, page_id)


def get_page_by_doc_page(db: Session, knowledge_id: int, page_no: int) -> Optional[KnowledgePage]:
    stmt = select(KnowledgePage).where(
        KnowledgePage.knowledge_id == knowledge_id,
        KnowledgePage.page_no == page_no,
    )
    return db.execute(stmt).scalar_one_or_none()


def list_pages(
    db: Session,
    knowledge_id: int,
    *,
    offset: int = 0,
    limit: int = 500,
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
    db: Session,
    *,
    knowledge_id: int,
    page_no: int,
    image_url: str,
    commit: bool = True,
) -> KnowledgePage:
    obj = get_page_by_doc_page(db, knowledge_id, page_no)
    if obj:
        obj.image_url = image_url
        db.add(obj)
        _finalize(db, commit=commit)
        _refresh_if_possible(db, obj, commit=commit)
        return obj

    obj = KnowledgePage(knowledge_id=knowledge_id, page_no=page_no, image_url=image_url)
    db.add(obj)
    _finalize(db, commit=commit)
    _refresh_if_possible(db, obj, commit=commit)
    return obj


def bulk_create_pages(db: Session, knowledge_id: int, pages: list[dict], commit: bool = True) -> int:
    objs = [
        KnowledgePage(
            knowledge_id=knowledge_id,
            page_no=int(p["page_no"]),
            image_url=(p.get("image_url") or ""),
        )
        for p in pages
    ]
    db.add_all(objs)
    _finalize(db, commit=commit)
    return len(objs)


def delete_page(db: Session, page_id: int, commit: bool = True) -> bool:
    obj = get_page(db, page_id)
    if not obj:
        return False
    db.delete(obj)
    _finalize(db, commit=commit)
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
    commit: bool = True,
) -> KnowledgeChunk:
    obj = KnowledgeChunk(
        knowledge_id=knowledge_id,
        page_id=page_id,
        chunk_index=int(chunk_index),
        chunk_text=str(chunk_text),
        vector_memory=list(vector_memory),
    )
    db.add(obj)
    _finalize(db, commit=commit)
    _refresh_if_possible(db, obj, commit=commit)
    return obj


def upsert_chunk(
    db: Session,
    *,
    knowledge_id: int,
    page_id: Optional[int],
    chunk_index: int,
    chunk_text: str,
    vector_memory: VectorArray,
    commit: bool = True,
) -> KnowledgeChunk:
    obj = get_chunk_by_doc_index(db, knowledge_id, int(chunk_index))
    if obj:
        obj.page_id = page_id
        obj.chunk_text = str(chunk_text)
        obj.vector_memory = list(vector_memory)
        db.add(obj)
        _finalize(db, commit=commit)
        _refresh_if_possible(db, obj, commit=commit)
        return obj

    return create_chunk(
        db,
        knowledge_id=knowledge_id,
        page_id=page_id,
        chunk_index=int(chunk_index),
        chunk_text=str(chunk_text),
        vector_memory=list(vector_memory),
        commit=commit,
    )


def bulk_upsert_chunks(
    db: Session,
    knowledge_id: int,
    items: List[Dict[str, Any]],
    commit: bool = True,
    refresh: bool = False,
) -> List[KnowledgeChunk]:
    """
    refresh=False(기본): bulk 성능 우선
    refresh=True: 반환 객체들 refresh 수행(느림)
    """
    out: List[KnowledgeChunk] = []

    existing = db.execute(
        select(KnowledgeChunk.chunk_index, KnowledgeChunk.id).where(KnowledgeChunk.knowledge_id == knowledge_id)
    ).all()
    idx_to_id = {int(row[0]): int(row[1]) for row in existing}

    for it in items:
        idx = int(it["chunk_index"])
        if idx in idx_to_id:
            obj = db.get(KnowledgeChunk, idx_to_id[idx])
            if not obj:
                # 방어: idx_to_id에 있는데 row가 없으면 새로 생성
                obj = KnowledgeChunk(
                    knowledge_id=knowledge_id,
                    page_id=it.get("page_id"),
                    chunk_index=idx,
                    chunk_text=str(it["chunk_text"]),
                    vector_memory=list(it["vector_memory"]),
                )
                db.add(obj)
                out.append(obj)
                continue

            obj.page_id = it.get("page_id")
            obj.chunk_text = str(it["chunk_text"])
            obj.vector_memory = list(it["vector_memory"])
            db.add(obj)
            out.append(obj)
        else:
            obj = KnowledgeChunk(
                knowledge_id=knowledge_id,
                page_id=it.get("page_id"),
                chunk_index=idx,
                chunk_text=str(it["chunk_text"]),
                vector_memory=list(it["vector_memory"]),
            )
            db.add(obj)
            out.append(obj)

    _finalize(db, commit=commit)

    if refresh:
        for o in out:
            _refresh_if_possible(db, o, commit=commit)

    return out


def create_knowledge_chunks(
    db: Session,
    knowledge_id: int,
    chunks: list[str],
    vectors: list[list[float]],
    commit: bool = True,
) -> List[KnowledgeChunk]:
    """
    upload_pipeline용 배치 저장 (chunk_index는 1부터)
    """
    items: List[Dict[str, Any]] = []
    for i, (text, vec) in enumerate(zip(chunks, vectors), start=1):
        t = (text or "").strip()
        if not t or vec is None:
            continue
        items.append(
            {
                "page_id": None,
                "chunk_index": i,  # 1부터
                "chunk_text": t,
                "vector_memory": [float(x) for x in vec],
            }
        )
    if not items:
        return []
    return bulk_upsert_chunks(db, knowledge_id, items, commit=commit, refresh=False)


# upload_pipeline이 기존 이름(create_chunks)으로 호출해도 안 깨지게 alias 제공
def create_chunks(
    db: Session,
    knowledge_id: int,
    chunks: list[str],
    vectors: list[list[float]],
    commit: bool = True,
) -> List[KnowledgeChunk]:
    return create_knowledge_chunks(db, knowledge_id, chunks, vectors, commit=commit)


def delete_chunk(db: Session, chunk_id: int, commit: bool = True) -> bool:
    obj = get_chunk(db, chunk_id)
    if not obj:
        return False
    db.delete(obj)
    _finalize(db, commit=commit)
    return True


def delete_chunks_by_knowledge(db: Session, knowledge_id: int, commit: bool = True) -> int:
    rows = list_chunks(db, knowledge_id=knowledge_id, limit=10_000)
    for r in rows:
        db.delete(r)
    _finalize(db, commit=commit)
    return len(rows)


# =========================
# Candidate queries (DB only)
# =========================
def vector_candidates(
    db: Session,
    *,
    query_vector: VectorArray,
    knowledge_id: Optional[int] = None,
    limit: int = 100,
) -> List[Tuple[KnowledgeChunk, float]]:
    """
    pgvector cosine_distance 기반 후보 조회만 담당.
    """
    vec = [float(x) for x in list(query_vector)]
    dist = KnowledgeChunk.vector_memory.cosine_distance(vec).label("dist")
    stmt = select(KnowledgeChunk, dist).where(KnowledgeChunk.vector_memory.isnot(None))
    if knowledge_id is not None:
        stmt = stmt.where(KnowledgeChunk.knowledge_id == knowledge_id)
    stmt = stmt.order_by(dist).limit(min(max(int(limit), 1), 500))
    rows = db.execute(stmt).all()
    return [(c, float(d)) for (c, d) in rows if d is not None]


def trigram_candidates(
    db: Session,
    *,
    query_text: str,
    knowledge_id: Optional[int] = None,
    limit: int = 50,
    min_similarity: float = 0.12,
) -> List[Tuple[KnowledgeChunk, float]]:
    """
    pg_trgm 후보 조회(점수 기반)만 담당.
    - 확장/인덱스 없으면 DB에서 에러날 수 있음 -> 호출부에서 try/except 권장
    """
    qt = (query_text or "").strip()
    if not qt:
        return []

    col_norm = getattr(KnowledgeChunk, "chunk_text_norm", None)
    if col_norm is not None:
        q = "".join(qt.split())[:200]
        col = col_norm
    else:
        q = qt[:200]
        col = KnowledgeChunk.chunk_text

    sim = func.similarity(col, q).label("sim")
    stmt = select(KnowledgeChunk, sim)
    if knowledge_id is not None:
        stmt = stmt.where(KnowledgeChunk.knowledge_id == knowledge_id)

    stmt = stmt.where(col.op("%")(q))
    stmt = stmt.where(sim >= float(min_similarity))
    stmt = stmt.order_by(sim.desc()).limit(min(max(int(limit), 1), 500))

    rows = db.execute(stmt).all()
    return [(c, float(s)) for (c, s) in rows if s is not None]


def chunks_by_ids(db: Session, ids: List[int]) -> List[KnowledgeChunk]:
    """
    id 리스트로 chunk 조회(입력 순서 유지)
    """
    if not ids:
        return []
    rows = db.execute(select(KnowledgeChunk).where(KnowledgeChunk.id.in_(ids))).scalars().all()
    by_id = {int(r.id): r for r in rows if getattr(r, "id", None) is not None}
    return [by_id[i] for i in ids if i in by_id]


# =========================
# Vector search (used by qa_chain)
# =========================
def search_chunks_by_vector(
    db: Session,
    *,
    query_vector: VectorArray,
    knowledge_id: Optional[int] = None,
    top_k: int = 5,
    query_text: Optional[str] = None,
) -> List[KnowledgeChunk]:
    """
    upload/rag에서 쓰는 기본 검색 API.
    - 1) vector 후보(top_k) 우선
    - 2) 부족하면 trigram(pg_trgm) 시도
    - 3) 그래도 부족/실패하면 ilike 폴백
    - 4) 최후 폴백: 앞쪽 청크
    """
    k = max(1, min(int(top_k or 5), 200))
    qt = (query_text or "").strip() if query_text else None

    try:
        _maybe_set_ivfflat_probes(db)

        # 1) vector
        vrows = vector_candidates(db, query_vector=query_vector, knowledge_id=knowledge_id, limit=k)
        rows: List[KnowledgeChunk] = [c for (c, _d) in vrows]

        if not rows:
            return _fallback_chunks(db, knowledge_id=knowledge_id, k=k, query_text=qt)

        # 2) 부족하면 trigram -> 실패하면 ilike
        if qt and len(rows) < k:
            exclude = {int(r.id) for r in rows if getattr(r, "id", None) is not None}

            more: List[KnowledgeChunk] = []
            try:
                trows = trigram_candidates(db, query_text=qt, knowledge_id=knowledge_id, limit=(k - len(rows)))
                more = [c for (c, _s) in trows if getattr(c, "id", None) not in exclude]
            except Exception:
                more = []

            if not more:
                more = _keyword_fallback_ilike(
                    db,
                    knowledge_id=knowledge_id,
                    k=(k - len(rows)),
                    query_text=qt,
                    exclude_ids=exclude,
                )

            rows.extend(more)

        return rows[:k]

    except Exception as e:
        log.exception("search_chunks_by_vector failed. knowledge_id=%s err=%s", knowledge_id, e)
        return _fallback_chunks(db, knowledge_id=knowledge_id, k=k, query_text=qt)


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


# ===== Convenience wrappers (keep) =====
from typing import Optional as _Optional
from typing import List as _List, Dict as _Dict, Any as _Any


def bulk_create_pages_any(db: Session, items: _List[_Dict[str, _Any]], commit: bool = True) -> _List[KnowledgePage]:
    objs: _List[KnowledgePage] = []
    for p in items:
        obj = KnowledgePage(
            knowledge_id=int(p["knowledge_id"]),
            page_no=int(p["page_no"]),
            image_url=str(p.get("image_url") or ""),
        )
        db.add(obj)
        objs.append(obj)
    _finalize(db, commit=commit)
    # bulk는 기본 refresh 안 함(필요하면 호출부에서 개별 refresh)
    return objs


def create_chunk_with_default_vector(
    db: Session,
    *,
    knowledge_id: int,
    page_id: _Optional[int],
    chunk_index: int,
    chunk_text: str,
    vector_memory: _Optional[VectorArray],
    vector_dim: int = 1536,
    commit: bool = True,
) -> KnowledgeChunk:
    vec = list(vector_memory) if vector_memory is not None else [0.0] * int(vector_dim)
    return create_chunk(
        db,
        knowledge_id=knowledge_id,
        page_id=page_id,
        chunk_index=chunk_index,
        chunk_text=chunk_text,
        vector_memory=vec,
        commit=commit,
    )


def upsert_chunk_with_default_vector(
    db: Session,
    *,
    knowledge_id: int,
    page_id: _Optional[int],
    chunk_index: int,
    chunk_text: str,
    vector_memory: _Optional[VectorArray],
    vector_dim: int = 1536,
    commit: bool = True,
) -> KnowledgeChunk:
    vec = list(vector_memory) if vector_memory is not None else [0.0] * int(vector_dim)
    return upsert_chunk(
        db,
        knowledge_id=knowledge_id,
        page_id=page_id,
        chunk_index=chunk_index,
        chunk_text=chunk_text,
        vector_memory=vec,
        commit=commit,
    )


def bulk_upsert_chunks_with_default(
    db: Session,
    knowledge_id: int,
    raw_items: _List[_Dict[str, _Any]],
    vector_dim: int = 1536,
    commit: bool = True,
) -> _List[KnowledgeChunk]:
    items: _List[_Dict[str, _Any]] = []
    for it in raw_items:
        vec = it.get("vector_memory")
        if vec is None:
            vec = [0.0] * int(vector_dim)
        items.append(
            {
                "page_id": it.get("page_id"),
                "chunk_index": int(it["chunk_index"]),
                "chunk_text": str(it["chunk_text"]),
                "vector_memory": list(vec),
            }
        )
    return bulk_upsert_chunks(db, knowledge_id, items, commit=commit, refresh=False)


# =========================================================
# nocommit aliases (편하게 쓰기)
# =========================================================
def create_knowledge_nocommit(db: Session, data: dict) -> Knowledge:
    return create_knowledge(db, data, commit=False)


def update_knowledge_nocommit(db: Session, knowledge_id: int, data: Dict[str, Any]) -> Optional[Knowledge]:
    return update_knowledge(db, knowledge_id, data, commit=False)


def delete_knowledge_nocommit(db: Session, knowledge_id: int) -> bool:
    return delete_knowledge(db, knowledge_id, commit=False)


def upsert_page_nocommit(db: Session, *, knowledge_id: int, page_no: int, image_url: str) -> KnowledgePage:
    return upsert_page(db, knowledge_id=knowledge_id, page_no=page_no, image_url=image_url, commit=False)


def create_chunk_nocommit(
    db: Session,
    *,
    knowledge_id: int,
    page_id: Optional[int],
    chunk_index: int,
    chunk_text: str,
    vector_memory: VectorArray,
) -> KnowledgeChunk:
    return create_chunk(
        db,
        knowledge_id=knowledge_id,
        page_id=page_id,
        chunk_index=chunk_index,
        chunk_text=chunk_text,
        vector_memory=vector_memory,
        commit=False,
    )


def upsert_chunk_nocommit(
    db: Session,
    *,
    knowledge_id: int,
    page_id: Optional[int],
    chunk_index: int,
    chunk_text: str,
    vector_memory: VectorArray,
) -> KnowledgeChunk:
    return upsert_chunk(
        db,
        knowledge_id=knowledge_id,
        page_id=page_id,
        chunk_index=chunk_index,
        chunk_text=chunk_text,
        vector_memory=vector_memory,
        commit=False,
    )


def upsert_chunk_with_default_vector_nocommit(
    db: Session,
    *,
    knowledge_id: int,
    page_id: Optional[int],
    chunk_index: int,
    chunk_text: str,
    vector_memory: Optional[VectorArray],
    vector_dim: int = 1536,
) -> KnowledgeChunk:
    return upsert_chunk_with_default_vector(
        db,
        knowledge_id=knowledge_id,
        page_id=page_id,
        chunk_index=chunk_index,
        chunk_text=chunk_text,
        vector_memory=vector_memory,
        vector_dim=vector_dim,
        commit=False,
    )
