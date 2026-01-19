# service/chat_history.py
from __future__ import annotations

import re
import logging
from collections import Counter, defaultdict
from datetime import date, datetime, timezone, timedelta, time
from typing import Optional, List, Dict, Any, Tuple

from sqlalchemy import select, text as sa_text
from sqlalchemy.orm import Session

from models.chat import ChatSession, Message
from crud import chat_history as crud

log = logging.getLogger("chat_history")


# =========================
# Keyword extraction (v2: mecab-ko + fallback)
# =========================
_STOPWORDS_KO = {
    "그리고", "그래서", "근데", "그런데", "또", "또는", "때문", "때문에",
    "이거", "저거", "그거", "이것", "저것", "그것", "여기", "저기",
    "합니다", "하는", "해서", "하면", "했어", "해야", "되나요", "됩니다",
    "가능", "불가", "오류", "에러", "문제", "해결", "방법",
    "좀", "진짜", "그냥",
}

_TOKEN_RE = re.compile(r"[가-힣A-Za-z0-9]+")
_HANGUL_RE = re.compile(r"^[가-힣]+$")

_MECAB_KIND: Optional[str] = None
_MECAB_OBJ: Any = None


def _init_mecab() -> None:
    global _MECAB_KIND, _MECAB_OBJ
    if _MECAB_OBJ is not None:
        return

    try:
        import MeCab  # type: ignore
        _MECAB_OBJ = MeCab.Tagger()
        _MECAB_KIND = "mecab-python3"
        log.info("mecab enabled: mecab-python3")
        return
    except Exception:
        pass

    try:
        from konlpy.tag import Mecab  # type: ignore
        _MECAB_OBJ = Mecab()
        _MECAB_KIND = "konlpy"
        log.info("mecab enabled: konlpy.tag.Mecab")
        return
    except Exception:
        _MECAB_OBJ = None
        _MECAB_KIND = None
        log.warning("mecab not available; fallback to simple keyword extraction")


_init_mecab()


def _mecab_pos(text: str) -> List[Tuple[str, str]]:
    if not _MECAB_OBJ or not _MECAB_KIND:
        return []

    if _MECAB_KIND == "konlpy":
        return list(_MECAB_OBJ.pos(text))  # type: ignore[attr-defined]

    try:
        node = _MECAB_OBJ.parseToNode(text)  # type: ignore[attr-defined]
        out: List[Tuple[str, str]] = []
        while node:
            surf = node.surface or ""
            feat = node.feature or ""
            pos = feat.split(",", 1)[0] if feat else ""
            if surf:
                out.append((surf, pos))
            node = node.next
        return out
    except Exception:
        return []


def extract_keywords_simple(text: str, *, max_keywords: int = 10) -> List[str]:
    if not text:
        return []
    tokens = _TOKEN_RE.findall(text)
    tokens = [t.strip().lower() for t in tokens if t.strip()]
    tokens = [t for t in tokens if len(t) >= 2 and t not in _STOPWORDS_KO]
    tokens = [t for t in tokens if not t.isdigit()]
    cnt = Counter(tokens)
    return [w for (w, _) in cnt.most_common(max_keywords)]


def _add_compound(out_tokens: List[str], noun_seq: List[str]) -> None:
    clean = [n for n in noun_seq if n and n not in _STOPWORDS_KO]
    if len(clean) < 2:
        return

    max_n = min(3, len(clean))
    for n in range(2, max_n + 1):
        for i in range(0, len(clean) - n + 1):
            phrase = " ".join(clean[i : i + n]).strip()
            if phrase and len(phrase) >= 2:
                out_tokens.append(phrase)


def extract_keywords_mecab(text: str, *, max_keywords: int = 10) -> List[str]:
    if not text:
        return []

    text = text.strip()
    if len(text) > 5000:
        text = text[:5000]

    pos_list = _mecab_pos(text)
    if not pos_list:
        return extract_keywords_simple(text, max_keywords=max_keywords)

    allowed = {"NNG", "NNP", "SL", "SN"}
    tokens: List[str] = []

    for surf, pos in pos_list:
        if pos not in allowed:
            continue

        tok = surf.strip()
        if not tok:
            continue

        if pos in {"SL", "SN"}:
            tok = tok.lower()

        if tok.isdigit():
            continue

        if _HANGUL_RE.match(tok):
            pass
        else:
            if len(tok) < 2:
                continue

        if tok in _STOPWORDS_KO:
            continue

        tokens.append(tok)

    noun_buf: List[str] = []
    for surf, pos in pos_list:
        if pos in {"NNG", "NNP"} and surf.strip():
            noun_buf.append(surf.strip())
            continue
        if noun_buf:
            _add_compound(tokens, noun_buf)
            noun_buf = []
    if noun_buf:
        _add_compound(tokens, noun_buf)

    cnt = Counter(tokens)
    return [w for (w, _) in cnt.most_common(max_keywords)]


def extract_keywords(text: str, *, max_keywords: int = 10) -> List[str]:
    if _MECAB_OBJ:
        return extract_keywords_mecab(text, max_keywords=max_keywords)
    return extract_keywords_simple(text, max_keywords=max_keywords)


# =========================
# Failure heuristic (v1: simple)
# =========================
_FAIL_PATTERNS = [
    re.compile(r"관련\s*자료.*없", re.IGNORECASE),
    re.compile(r"문서.*없", re.IGNORECASE),
    re.compile(r"찾지\s*못", re.IGNORECASE),
    re.compile(r"확인\s*질문", re.IGNORECASE),
]


def _is_failed_assistant_message(msg: Message) -> bool:
    if msg.role != "assistant":
        return False

    ex = (msg.extra_data or {}) if isinstance(msg.extra_data, dict) else {}
    if bool(ex.get("no_context")) or bool(ex.get("need_clarify")) or bool(ex.get("retrieval_failed")):
        return True

    content = msg.content or ""
    return any(p.search(content) for p in _FAIL_PATTERNS)


# =========================
# QuickCategory helpers
# =========================
def _load_quick_category_maps(db: Session) -> Tuple[Dict[str, int], Dict[int, str]]:
    """
    (name_lower -> id), (id -> name)
    """
    rows = db.execute(sa_text("SELECT id, name FROM quick_category")).mappings().all()
    name_to_id: Dict[str, int] = {}
    id_to_name: Dict[int, str] = {}
    for r in rows:
        _id = int(r["id"])
        name = str(r.get("name") or "").strip()
        if not name:
            continue
        name_to_id[name.lower()] = _id
        id_to_name[_id] = name
    return name_to_id, id_to_name


def _norm_for_match(s: str) -> str:
    # 공백 제거 + 소문자
    return re.sub(r"\s+", "", (s or "").strip().lower())


def _infer_quick_category_id_from_text(
    text: Optional[str],
    *,
    name_to_id: Dict[str, int],
) -> Optional[int]:
    """
    매우 단순 룰:
    - 질문 텍스트(공백 제거) 안에 quick_category.name(공백 제거)가 포함되면 매칭
    - 여러 개면 "가장 긴 name" 우선(짧은 토큰에 과매칭 방지)
    """
    if not text:
        return None

    qn = _norm_for_match(text)
    if not qn:
        return None

    # 긴 이름 우선
    candidates = sorted(name_to_id.keys(), key=lambda x: len(_norm_for_match(x)), reverse=True)
    for name in candidates:
        nn = _norm_for_match(name)
        if nn and nn in qn:
            return int(name_to_id[name])
    return None


# =========================
# Build / rebuild
# =========================
def rebuild_range(db: Session, *, date_from: date, date_to: date) -> Dict[str, Any]:
    dt_from = datetime.combine(date_from, time.min, tzinfo=timezone.utc)
    dt_to_excl = datetime.combine(date_to + timedelta(days=1), time.min, tzinfo=timezone.utc)

    sessions: List[ChatSession] = db.execute(
        select(ChatSession).where(
            ChatSession.created_at >= dt_from,
            ChatSession.created_at < dt_to_excl,
        ).order_by(ChatSession.created_at.asc())
    ).scalars().all()

    session_ids = [int(s.id) for s in sessions]
    if not session_ids:
        crud.delete_keyword_daily_range(db, date_from=date_from, date_to=date_to)
        db.commit()
        return {"sessions": 0, "messages": 0, "keywords": 0, "suggestions": 0}

    msgs: List[Message] = db.execute(
        select(Message).where(Message.session_id.in_(session_ids)).order_by(Message.created_at.asc())
    ).scalars().all()

    by_session: Dict[int, List[Message]] = defaultdict(list)
    for m in msgs:
        by_session[int(m.session_id)].append(m)

    # quick_category maps + etc_id
    qc_name_to_id, qc_id_to_name = _load_quick_category_maps(db)
    etc_id: Optional[int] = qc_name_to_id.get("etc")

    # 1) session_insight 업데이트
    updated_sessions = 0
    session_insight_cache: Dict[int, Any] = {}

    for s in sessions:
        sid = int(s.id)
        mlist = by_session.get(sid, [])

        user_msgs = [m for m in mlist if m.role == "user"]
        first_q = (user_msgs[0].content if user_msgs else None)
        qcount = len(user_msgs)

        failed_msg = next((m for m in reversed(mlist) if _is_failed_assistant_message(m)), None)
        status = "failed" if failed_msg else "success"
        failed_reason = (failed_msg.content[:200] if failed_msg else None)

        # ✅ channel 복제(세션에 채널 컬럼이 있으면 그걸로)
        raw_channel = getattr(s, "channel", None)
        channel_norm: Optional[str] = None
        if raw_channel is not None:
            channel_norm = str(raw_channel).strip().lower() or None

        si = crud.upsert_session_insight(
            db,
            session_id=sid,
            started_at=s.created_at,
            channel=channel_norm,
            status=status,
            first_question=(first_q[:300] if first_q else None),
            question_count=qcount,
            failed_reason=failed_reason,
            # category는 "캐시"지만, 아래에서 비어있으면 채워줄 거야
        )

        # ✅ quick_category_id 확정 로직
        qc_id_curr = getattr(si, "quick_category_id", None)

        # 케이스 1) 비어있으면 추정 → 없으면 etc
        if qc_id_curr is None:
            inferred = _infer_quick_category_id_from_text(first_q, name_to_id=qc_name_to_id)
            if inferred is not None:
                si.quick_category_id = int(inferred)
            elif etc_id is not None:
                si.quick_category_id = int(etc_id)

        # 케이스 2) 이미 etc인데 category까지 비어 있으면(“전부 etc” 방어) 한번 더 추정 시도
        else:
            try:
                qc_id_int = int(qc_id_curr)
            except Exception:
                qc_id_int = None

            if qc_id_int is not None and etc_id is not None and qc_id_int == int(etc_id):
                if not (getattr(si, "category", None) or "").strip():
                    inferred = _infer_quick_category_id_from_text(first_q, name_to_id=qc_name_to_id)
                    if inferred is not None and inferred != int(etc_id):
                        si.quick_category_id = int(inferred)

        # ✅ category 캐시(name) 채우기: null이면 quick_category_id의 name으로 채움
        if not (getattr(si, "category", None) or "").strip():
            qc_id_final = getattr(si, "quick_category_id", None)
            try:
                qc_id_final_int = int(qc_id_final) if qc_id_final is not None else None
            except Exception:
                qc_id_final_int = None

            if qc_id_final_int is not None:
                nm = qc_id_to_name.get(qc_id_final_int)
                if nm:
                    si.category = nm

        session_insight_cache[sid] = si
        updated_sessions += 1

    # 2) message_insight 업데이트 + 키워드 메모(집계용)
    updated_messages = 0
    msg_keywords: Dict[int, List[str]] = {}

    for m in msgs:
        if m.role != "user":
            continue
        kws = extract_keywords(m.content or "", max_keywords=10)
        msg_keywords[int(m.id)] = kws

        crud.upsert_message_insight(
            db,
            message_id=int(m.id),
            session_id=int(m.session_id),
            is_question=True,
            keywords=kws or None,
            created_at=m.created_at,
        )
        updated_messages += 1

    # 2.6) knowledge_suggestion 자동 생성(실패 세션)
    updated_suggestions = 0
    for sid, mlist in by_session.items():
        si = session_insight_cache.get(int(sid))
        if not si:
            continue
        if str(getattr(si, "status", "success")) != "failed":
            continue

        failed_msg = next((m for m in reversed(mlist) if _is_failed_assistant_message(m)), None)
        if not failed_msg:
            continue

        # 실패 assistant 직전의 마지막 user 질문을 찾기
        question_msg: Optional[Message] = None
        if failed_msg in mlist:
            idx = mlist.index(failed_msg)
            for j in range(idx - 1, -1, -1):
                if mlist[j].role == "user":
                    question_msg = mlist[j]
                    break
        if question_msg is None:
            question_msg = next((m for m in reversed(mlist) if m.role == "user"), None)

        if not question_msg:
            continue

        # 멱등 upsert (ingested/deleted는 보호됨)
        crud.upsert_pending_knowledge_suggestion(
            db,
            session_id=int(sid),
            message_id=int(question_msg.id),
            question_text=str(question_msg.content or "").strip()[:5000],
            assistant_answer=str(failed_msg.content or "").strip()[:5000],
            reason_code="REBUILD_FAILED_SESSION",
            retrieval_meta={"source": "rebuild_range"},
            answer_status="error",
        )
        updated_suggestions += 1

    # 3) keyword_daily 재집계 (category 제거 -> quick_category_id 사용)
    crud.delete_keyword_daily_range(db, date_from=date_from, date_to=date_to)

    acc: Dict[Tuple[date, str, Optional[str], Optional[int]], int] = defaultdict(int)

    for m in msgs:
        if m.role != "user":
            continue

        dt = m.created_at.astimezone(timezone.utc).date()
        si = session_insight_cache.get(int(m.session_id))
        ch = getattr(si, "channel", None) if si else None

        qc_id = getattr(si, "quick_category_id", None) if si else None
        if qc_id is None and etc_id is not None:
            qc_id = int(etc_id)

        kws = msg_keywords.get(int(m.id), [])
        for kw in kws:
            acc[(dt, str(kw), ch, (int(qc_id) if qc_id is not None else None))] += 1

    for (dt, kw, ch, qc_id), c in acc.items():
        crud.upsert_keyword_daily_set(
            db,
            dt=dt,
            keyword=kw,
            count=c,
            channel=ch,
            quick_category_id=qc_id,
        )

    db.commit()
    return {
        "sessions": updated_sessions,
        "messages": updated_messages,
        "keywords": len(acc),
        "suggestions": updated_suggestions,
    }
