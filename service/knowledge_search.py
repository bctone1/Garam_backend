# service/knowledge_search.py
from __future__ import annotations

import logging
import math
from typing import Optional, List, Sequence

from sqlalchemy import select, text as sql_text
from sqlalchemy.orm import Session

from models.knowledge import KnowledgeChunk

log = logging.getLogger("knowledge_search")
VectorArray = Sequence[float]


def _sanitize_vector(v: VectorArray) -> List[float]:
    if v is None:
        return []
    out: List[float] = []
    for x in v:
        try:
            f = float(x)
        except Exception:
            continue
        if not math.isfinite(f):
            f = 0.0
        out.append(f)
    return out


def _maybe_set_ivfflat_probes(db: Session) -> None:
    try:
        import core.config as config
        probes = getattr(config, "IVFFLAT_PROBES", None)
        if probes is None:
            return
        p = int(probes)
        if p > 0:
            db.execute(sql_text("SET LOCAL ivfflat.probes = :p"), {"p": p})
    except Exception:
        return


def _keyword_trgm(
    db: Session,
    *,
    knowledge_id: Optional[int],
    query_text: str,
    k: int,
    exclude_ids: Optional[set[int]] = None,
) -> List[KnowledgeChunk]:
    """
    pg_trgm 인덱스(idx_kchunk_text_norm_trgm) 전제:
    - chunk_text_norm % : trigram similarity 매칭
    - 공백/개행 분절(사\n훈)은 norm 컬럼에서 제거되어 잡힘
    """
    qt = (query_text or "").strip()
    if not qt:
        return []
    qt = qt[:200]

    # chunk_text_norm은 whitespace 제거한 lower 텍스트이므로 query도 동일 정규화해서 매칭
    qt_norm = "".join(qt.split()).lower()

    stmt = select(KnowledgeChunk).where(
        sql_text("chunk_text_norm % :q")  # trigram operator
    )
    if knowledge_id is not None:
        stmt = stmt.where(KnowledgeChunk.knowledge_id == knowledge_id)

    # 가장 비슷한 것부터
    stmt = stmt.order_by(sql_text("similarity(chunk_text_norm, :q) DESC")).params(q=qt_norm).limit(min(k * 5, 200))
    rows = db.execute(stmt).scalars().all()

    if exclude_ids:
        rows = [r for r in rows if r.id is not None and int(r.id) not in exclude_ids]
    return rows[:k]


def search_chunks_by_vector(
    db: Session,
    *,
    query_vector: VectorArray,
    knowledge_id: Optional[int] = None,
    top_k: int = 8,
    query_text: Optional[str] = None,
) -> List[KnowledgeChunk]:
    """
    단순화:
    1) 벡터 top_k 후보
    2) 부족분만 trgm 키워드로 보강
    3) 둘 다 실패하면 빈 리스트(컨텍스트 오염 방지)
    """
    k = max(1, min(int(top_k or 8), 50))

    vec = _sanitize_vector(query_vector)
    rows: List[KnowledgeChunk] = []
    ids: set[int] = set()

    if vec:
        try:
            _maybe_set_ivfflat_probes(db)
            stmt = select(KnowledgeChunk).where(KnowledgeChunk.vector_memory.isnot(None))
            if knowledge_id is not None:
                stmt = stmt.where(KnowledgeChunk.knowledge_id == knowledge_id)

            stmt = stmt.order_by(KnowledgeChunk.vector_memory.cosine_distance(vec)).limit(k)
            rows = db.execute(stmt).scalars().all()
            ids = {int(r.id) for r in rows if r.id is not None}
        except Exception as e:
            log.exception("vector search failed: %s", e)
            rows = []
            ids = set()

    # 키워드 보강(사훈 같은 exact/short query가 여기서 잘 잡힘)
    if query_text and len(rows) < k:
        try:
            more = _keyword_trgm(
                db,
                knowledge_id=knowledge_id,
                query_text=query_text,
                k=(k - len(rows)),
                exclude_ids=ids,
            )
            for m in more:
                mid = int(m.id)
                if mid not in ids:
                    rows.append(m)
                    ids.add(mid)
        except Exception as e:
            log.warning("keyword trgm fallback failed: %s", e)

    return rows[:k]
