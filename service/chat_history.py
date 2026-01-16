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
            # 한글은 1글자도 의미 있을 수 있어 허용
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
def _load_quick_category_name_map(db: Session) -> Dict[str, int]:
    """
    quick_category.name(lower) -> id
    """
    rows = db.execute(sa_text("SELECT id, name FROM quick_category")).mappings().all()
    out: Dict[str, int] = {}
    for r in rows:
        name = str(r.get("name") or "").strip().lower()
        if not name:
            continue
        out[name] = int(r["id"])
    return out


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
        return {"sessions": 0, "messages": 0, "keywords": 0}

    msgs: List[Message] = db.execute(
        select(Message).where(Message.session_id.in_(session_ids)).order_by(Message.created_at.asc())
    ).scalars().all()

    by_session: Dict[int, List[Message]] = defaultdict(list)
    for m in msgs:
        by_session[int(m.session_id)].append(m)

    # quick_category name->id 맵 + etc_id
    qc_name_map = _load_quick_category_name_map(db)
    etc_id: Optional[int] = qc_name_map.get("etc")

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

        si = crud.upsert_session_insight(
            db,
            session_id=sid,
            started_at=s.created_at,
            status=status,
            first_question=(first_q[:300] if first_q else None),
            question_count=qcount,
            failed_reason=failed_reason,
            # category는 캐시용이므로 rebuild에서 굳이 덮어쓰지 않음
        )

        # quick_category_id가 비어 있으면: (category 캐시가 있으면 매핑) -> 없으면 etc
        if getattr(si, "quick_category_id", None) is None:
            cat = getattr(si, "category", None)
            mapped = qc_name_map.get(str(cat).strip().lower()) if cat else None
            if mapped is not None:
                si.quick_category_id = int(mapped)
            elif etc_id is not None:
                si.quick_category_id = int(etc_id)

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
    return {"sessions": updated_sessions, "messages": updated_messages, "keywords": len(acc)}
