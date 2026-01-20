# service/knowledge_retrieval.py
from __future__ import annotations

import logging
import math
from typing import Optional, Sequence, List, Tuple, Callable

from sqlalchemy.orm import Session
from sqlalchemy import text as sql_text

from crud import knowledge as crud_knowledge
from models.knowledge import KnowledgeChunk

log = logging.getLogger("knowledge_retrieval")
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


def retrieve_candidates_hybrid(
    db: Session,
    *,
    query_text: str,
    query_vector: VectorArray,
    knowledge_id: Optional[int] = None,
    vector_k: int = 100,
    trigram_k: int = 50,
    min_trgm_similarity: float = 0.12,
) -> Tuple[List[Tuple[KnowledgeChunk, float]], List[Tuple[KnowledgeChunk, float]]]:
    """
    - vector 후보(거리) + trigram 후보(유사도) 각각 반환
    - merge/rerank/topK는 아래 retrieve_topk_hybrid에서 처리
    """
    vec = _sanitize_vector(query_vector)
    _maybe_set_ivfflat_probes(db)

    vec_pairs: List[Tuple[KnowledgeChunk, float]] = []
    if vec:
        vec_pairs = crud_knowledge.vector_candidates(
            db,
            query_vector=vec,
            knowledge_id=knowledge_id,
            limit=vector_k,
        )

    trgm_pairs = crud_knowledge.trigram_candidates(
        db,
        query_text=query_text,
        knowledge_id=knowledge_id,
        limit=trigram_k,
        min_similarity=min_trgm_similarity,
    )

    return vec_pairs, trgm_pairs


def retrieve_topk_hybrid(
    db: Session,
    *,
    query_text: str,
    query_vector: VectorArray,
    knowledge_id: Optional[int] = None,
    top_k: int = 8,
    vector_k: int = 100,
    trigram_k: int = 50,
    min_trgm_similarity: float = 0.12,
    rerank: Optional[Callable[[str, List[KnowledgeChunk]], List[KnowledgeChunk]]] = None,
) -> List[KnowledgeChunk]:
    """
    기본 정책:
    - 후보는 넉넉히(vector_k, trigram_k) 가져온다
    - merge 후(중복 제거) top_k는 rerank가 있으면 rerank로, 없으면 간단한 휴리스틱 정렬로 반환
    """
    top_k = max(1, min(int(top_k or 8), 50))

    vec_pairs, trgm_pairs = retrieve_candidates_hybrid(
        db,
        query_text=query_text,
        query_vector=query_vector,
        knowledge_id=knowledge_id,
        vector_k=vector_k,
        trigram_k=trigram_k,
        min_trgm_similarity=min_trgm_similarity,
    )

    # merge (id 기준)
    by_id: dict[int, dict] = {}

    for c, dist in vec_pairs:
        cid = int(c.id)
        by_id.setdefault(cid, {"chunk": c, "dist": None, "sim": None})
        by_id[cid]["dist"] = float(dist)

    for c, sim in trgm_pairs:
        cid = int(c.id)
        by_id.setdefault(cid, {"chunk": c, "dist": None, "sim": None})
        by_id[cid]["sim"] = float(sim)

    merged: List[KnowledgeChunk] = [v["chunk"] for v in by_id.values()]
    if not merged:
        return []

    # rerank hook (추후 cross-encoder/LLM rerank 여기로)
    if rerank is not None:
        try:
            ranked = rerank(query_text, merged)
            return ranked[:top_k]
        except Exception as e:
            log.warning("rerank failed, fallback to heuristic. err=%s", e)

    # heuristic 정렬: trigram(sim) 우선, 그 다음 vector(dist) 보조
    def score(cid: int) -> tuple:
        item = by_id[cid]
        sim = item["sim"]
        dist = item["dist"]
        has_sim = 1 if sim is not None else 0
        sim_val = float(sim) if sim is not None else 0.0
        dist_val = float(dist) if dist is not None else 1e9
        # sim 내림차순, dist 오름차순
        return (has_sim, sim_val, -dist_val)

    ids_sorted = sorted(by_id.keys(), key=score, reverse=True)
    out = [by_id[i]["chunk"] for i in ids_sorted][:top_k]
    return out


def retrieve_topk_hybrid_with_scores(
    db: Session,
    *,
    query_text: str,
    query_vector: VectorArray,
    knowledge_id: Optional[int] = None,
    top_k: int = 8,
    vector_k: int = 100,
    trigram_k: int = 50,
    min_trgm_similarity: float = 0.12,
    rerank: Optional[Callable[[str, List[KnowledgeChunk]], List[KnowledgeChunk]]] = None,
) -> tuple[List[KnowledgeChunk], dict[int, dict[str, float | None]], Optional[float]]:
    top_k = max(1, min(int(top_k or 8), 50))

    vec_pairs, trgm_pairs = retrieve_candidates_hybrid(
        db,
        query_text=query_text,
        query_vector=query_vector,
        knowledge_id=knowledge_id,
        vector_k=vector_k,
        trigram_k=trigram_k,
        min_trgm_similarity=min_trgm_similarity,
    )

    by_id: dict[int, dict] = {}
    for c, dist in vec_pairs:
        cid = int(c.id)
        by_id.setdefault(cid, {"chunk": c, "dist": None, "sim": None})
        by_id[cid]["dist"] = float(dist)

    for c, sim in trgm_pairs:
        cid = int(c.id)
        by_id.setdefault(cid, {"chunk": c, "dist": None, "sim": None})
        by_id[cid]["sim"] = float(sim)

    merged: List[KnowledgeChunk] = [v["chunk"] for v in by_id.values()]
    if not merged:
        return [], {}, None

    if rerank is not None:
        try:
            ranked = rerank(query_text, merged)
            out = ranked[:top_k]
        except Exception as e:
            log.warning("rerank failed, fallback to heuristic. err=%s", e)
            out = []
    else:
        out = []

    if not out:
        def score(cid: int) -> tuple:
            item = by_id[cid]
            sim = item["sim"]
            dist = item["dist"]
            has_sim = 1 if sim is not None else 0
            sim_val = float(sim) if sim is not None else 0.0
            dist_val = float(dist) if dist is not None else 1e9
            return (has_sim, sim_val, -dist_val)

        ids_sorted = sorted(by_id.keys(), key=score, reverse=True)
        out = [by_id[i]["chunk"] for i in ids_sorted][:top_k]

    scores = {
        cid: {"sim": by_id[cid]["sim"], "dist": by_id[cid]["dist"]}
        for cid in by_id
    }
    max_sim = max((v["sim"] for v in scores.values() if v["sim"] is not None), default=None)
    return out, scores, float(max_sim) if max_sim is not None else None
