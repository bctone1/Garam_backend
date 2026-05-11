# service/memory/postgres_history.py
from __future__ import annotations

from typing import List, Optional, Any, Dict

from sqlalchemy import select
from sqlalchemy.orm import Session

from langchain_core.chat_history import BaseChatMessageHistory
from langchain_core.messages import BaseMessage, HumanMessage, AIMessage, SystemMessage

from models.chat import Message


class PostgresChatMessageHistory(BaseChatMessageHistory):
    """
    - messages: DB에서 최근 k개 로드
    - add_message: 들어오는 LangChain 메시지를 DB에 저장
    - set_last_ai_latency: 마지막 assistant 메시지의 latency 업데이트
    """

    def __init__(self, db: Session, session_id: int, k: int = 12):
        self.db = db
        self.session_id = int(session_id)
        self.k = max(1, int(k))
        self._last_ai_message_id: Optional[int] = None

    @property
    def messages(self) -> List[BaseMessage]:
        stmt = (
            select(Message)
            .where(Message.session_id == self.session_id)
            .order_by(Message.created_at.desc(), Message.id.desc())
            .limit(self.k)
        )
        rows = list(self.db.scalars(stmt).all())
        rows.reverse()  # 오래된 -> 최신 순으로

        out: List[BaseMessage] = []
        for r in rows:
            if r.role == "user":
                out.append(HumanMessage(content=r.content))
            elif r.role == "assistant":
                out.append(AIMessage(content=r.content))
        return out

    def add_message(self, message: BaseMessage) -> None:
        # DB 제약: role IN ('user','assistant') 이라 system은 저장 불가 -> 무시
        if isinstance(message, SystemMessage):
            return

        if isinstance(message, HumanMessage):
            role = "user"
        elif isinstance(message, AIMessage):
            role = "assistant"
        else:
            # 혹시 모르는 타입은 content만 살리고 user로 취급(원하면 여기서 raise 해도 됨)
            role = "user"

        extra: Optional[Dict[str, Any]] = None
        # LangChain 메시지 메타를 남기고 싶으면(선택)
        # if getattr(message, "additional_kwargs", None):
        #     extra = {"lc_additional_kwargs": message.additional_kwargs}

        obj = Message(
            session_id=self.session_id,
            role=role,
            content=message.content,
            response_latency_ms=None,  # assistant도 일단 null, 나중에 업데이트
            vector_memory=None,
            extra_data=extra,
        )
        self.db.add(obj)
        self.db.flush()  # id 확보

        if role == "assistant":
            self._last_ai_message_id = obj.id

    def clear(self) -> None:
        # 필요하면 구현. 운영에서는 보통 세션 종료(ended_at)만 찍고 메시지는 남김.
        stmt = select(Message.id).where(Message.session_id == self.session_id)
        ids = [x for x in self.db.scalars(stmt).all()]
        if not ids:
            return
        self.db.query(Message).filter(Message.id.in_(ids)).delete(synchronize_session=False)
        self.db.flush()

    def set_last_ai_latency(self, latency_ms: int) -> None:
        if self._last_ai_message_id is None:
            return
        msg = self.db.get(Message, self._last_ai_message_id)
        if not msg or msg.role != "assistant":
            return
        msg.response_latency_ms = max(0, int(latency_ms))
        self.db.flush()
