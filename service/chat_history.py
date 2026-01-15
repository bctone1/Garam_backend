# service/chat_history.py
from __future__ import annotations

import re
import logging
from collections import Counter, defaultdict
from datetime import date, datetime, timezone, timedelta, time
from typing import Optional, List, Dict, Any, Iterable, Tuple

from sqlalchemy import select
from sqlalchemy.orm import Session

from models.chat import ChatSession, Message
from crud import chat_history as crud

log = logging.getLogger("chat_history")


# =========================
# Keyword extraction (v1: simple)
# =========================
_STOPWORDS_KO = {
    "그리고", "그래서", "근데", "그런데", "또", "또는", "때문", "때문에",
    "이거", "저거", "그거", "이것", "저것", "그것", "여기", "저기",
    "합니다", "하는", "해서", "하면", "했어", "해야", "되나요", "됩니다",
    "가능", "불가", "오류", "에러", "문제", "해결", "방법",
    "좀", "진짜", "그냥",
}

_TOKEN_RE = re.compile(r"[가-힣A-Za-z0-9]+")


def extract_keywords_simple(text: str, *, max_keywords: int = 10) -> List[str]:
    """
    - v10.html이 프론트에서 하던 '간단 키워드' 방식과 비슷한 서버 버전
    - 형태소 분석/LLM 키워드는 v2에서 교체
    """
    if not text:
        return []

    tokens = _TOKEN_RE.findall(text)
    tokens = [t.strip().lower() for t in tokens if t.strip()]
    tokens = [t for t in tokens if len(t) >= 2 and t not in _STOPWORDS_KO]

    # 너무 숫자만인 토큰 제거(예: 01, 1234 등)
    tokens = [t for t in tokens if not t.isdigit()]

    cnt = Counter(tokens)
    return [w for (w, _) in cnt.most_common(max_keywords)]


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
    # 우선: 시스템/체인에서 실패 플래그를 넣었다면 그걸 신뢰
    if bool(ex.get("no_context")) or bool(ex.get("need_clarify")) or bool(ex.get("retrieval_failed")):
        return True

    content = msg.content or ""
    return any(p.search(content) for p in _FAIL_PATTERNS)


# =========================
# Build / rebuild
# =========================
def rebuild_range(db: Session, *, date_from: date, date_to: date) -> Dict[str, Any]:
    """
    기간 내 chat_session / message를 훑어서
    - chat_session_insight 업데이트
    - chat_message_insight(질문/키워드) 업데이트
    - chat_keyword_daily 재집계
    """
    # 1) 기간 세션 조회(UTC 기준, [from, to+1) )
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
        # 키워드 집계도 지울 필요가 있으면 여기서 delete_keyword_daily_range 호출
        crud.delete_keyword_daily_range(db, date_from=date_from, date_to=date_to)
        db.commit()
        return {"sessions": 0, "messages": 0, "keywords": 0}

    # 2) 세션별 메시지 로드(해당 세션의 모든 메시지)
    msgs: List[Message] = db.execute(
        select(Message).where(Message.session_id.in_(session_ids)).order_by(Message.created_at.asc())
    ).scalars().all()

    # 세션별 그룹
    by_session: Dict[int, List[Message]] = defaultdict(list)
    for m in msgs:
        by_session[int(m.session_id)].append(m)

    # 3) session_insight 업데이트
    updated_sessions = 0
    for s in sessions:
        sid = int(s.id)
        mlist = by_session.get(sid, [])

        user_msgs = [m for m in mlist if m.role == "user"]
        first_q = (user_msgs[0].content if user_msgs else None)
        qcount = len(user_msgs)

        failed_msg = next((m for m in reversed(mlist) if _is_failed_assistant_message(m)), None)
        status = "failed" if failed_msg else "success"
        failed_reason = (failed_msg.content[:200] if failed_msg else None)

        crud.upsert_session_insight(
            db,
            session_id=sid,
            started_at=s.created_at,
            status=status,
            first_question=(first_q[:300] if first_q else None),
            question_count=qcount,
            failed_reason=failed_reason,
            # channel/category는 v1에선 자동 추정 안 함(원하면 v2에서 추가)
        )
        updated_sessions += 1

    # 4) message_insight 업데이트(질문 + 키워드)
    updated_messages = 0
    for m in msgs:
        if m.role != "user":
            continue
        kws = extract_keywords_simple(m.content or "")
        crud.upsert_message_insight(
            db,
            message_id=int(m.id),
            session_id=int(m.session_id),
            is_question=True,
            keywords=kws or None,
            created_at=m.created_at,
        )
        updated_messages += 1

    # 5) keyword_daily 재집계: 기간 내 user 메시지의 keywords 기반
    #    - 먼저 기존 기간 집계 삭제 후, 새로 set/upsert
    crud.delete_keyword_daily_range(db, date_from=date_from, date_to=date_to)

    # (dt, keyword, channel, category) -> count
    acc: Dict[Tuple[date, str, Optional[str], Optional[str]], int] = defaultdict(int)

    # session insight 캐시(채널/카테고리)
    insight_map = {int(s.id): crud.get_session_insight(db, int(s.id)) for s in sessions}

    for m in msgs:
        if m.role != "user":
            continue
        mi = crud.get_message_insight(db, int(m.id))  # 방금 upsert 했으니 존재
        if not mi:
            continue

        dt = m.created_at.astimezone(timezone.utc).date()
        si = insight_map.get(int(m.session_id))
        ch = getattr(si, "channel", None) if si else None
        cat = getattr(mi, "category", None) or (getattr(si, "category", None) if si else None)

        kws = (getattr(mi, "keywords", None) or [])
        for kw in kws:
            key = (dt, str(kw), ch, cat)
            acc[key] += 1

    for (dt, kw, ch, cat), c in acc.items():
        crud.upsert_keyword_daily_set(db, dt=dt, keyword=kw, count=c, channel=ch, category=cat)

    db.commit()
    return {"sessions": updated_sessions, "messages": updated_messages, "keywords": len(acc)}
