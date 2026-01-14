# service/ws_manager.py
from __future__ import annotations

import asyncio
import threading
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Dict, Optional, Set


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


@dataclass
class WSConn:
    """
    set에 넣기 위해 해시/동등성은 객체 identity 기준으로 동작.
    (asyncio.Queue는 기본적으로 unhashable이라 dataclass(frozen) + set 조합이 깨짐)
    """
    admin_id: int
    ws: Any  # fastapi.WebSocket (순환 import 피하려고 Any)
    send_q: "asyncio.Queue[dict[str, Any]]"
    connected_at: datetime

    def __hash__(self) -> int:  # identity hash
        return id(self)

    def __eq__(self, other: object) -> bool:
        return self is other


class WSManager:
    """
    admin_id -> WebSocket 연결들 관리 + 타겟 publish.

    중요:
    - FastAPI의 sync endpoint(일반 def)는 threadpool에서 실행될 수 있음.
      그 안에서 publish하려면 publish_sync()로 event-loop에 안전하게 스케줄링해야 함.
    - websocket endpoint(async)에서는 publish()를 그냥 await로 써도 됨.
    """

    def __init__(self, *, queue_maxsize: int = 200) -> None:
        self._by_admin: dict[int, Set[WSConn]] = {}
        self._lock = asyncio.Lock()

        self._queue_maxsize = int(queue_maxsize)

        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self._loop_lock = threading.Lock()

    # -------------------------
    # loop 관리
    # -------------------------
    def set_loop(self, loop: asyncio.AbstractEventLoop) -> None:
        with self._loop_lock:
            self._loop = loop

    def _ensure_loop(self) -> None:
        # websocket 연결이 최초로 생길 때 loop를 저장
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            return
        with self._loop_lock:
            if self._loop is None:
                self._loop = loop

    def has_loop(self) -> bool:
        with self._loop_lock:
            return self._loop is not None

    # -------------------------
    # 연결 관리
    # -------------------------
    async def register(self, admin_id: int, ws: Any) -> WSConn:
        self._ensure_loop()

        # WebSocket.accept()는 websocket endpoint에서만 호출해야 함.
        await ws.accept()

        conn = WSConn(
            admin_id=admin_id,
            ws=ws,
            send_q=asyncio.Queue(maxsize=self._queue_maxsize),
            connected_at=_utcnow(),
        )

        async with self._lock:
            self._by_admin.setdefault(admin_id, set()).add(conn)

        # 연결 직후 hello(선택)
        self._enqueue(conn, {"type": "hello", "admin_id": admin_id})
        return conn

    async def unregister(self, admin_id: int, conn: WSConn) -> None:
        async with self._lock:
            conns = self._by_admin.get(admin_id)
            if not conns:
                return
            conns.discard(conn)
            if not conns:
                self._by_admin.pop(admin_id, None)

    async def connected_count(self, admin_id: Optional[int] = None) -> int:
        async with self._lock:
            if admin_id is None:
                return sum(len(v) for v in self._by_admin.values())
            return len(self._by_admin.get(admin_id, set()))

    async def connected_admin_ids(self) -> Set[int]:
        async with self._lock:
            return set(self._by_admin.keys())

    # -------------------------
    # publish (async)
    # -------------------------
    async def publish(self, admin_id: int, message: Dict[str, Any]) -> None:
        async with self._lock:
            conns = list(self._by_admin.get(admin_id, set()))
        for conn in conns:
            self._enqueue(conn, message)

    async def publish_many(self, admin_ids: Set[int], message: Dict[str, Any]) -> None:
        async with self._lock:
            conns: list[WSConn] = []
            for aid in admin_ids:
                conns.extend(list(self._by_admin.get(aid, set())))
        for conn in conns:
            self._enqueue(conn, message)

    # -------------------------
    # publish (sync-safe)
    # -------------------------
    def publish_sync(self, admin_id: int, message: Dict[str, Any]) -> bool:
        """
        sync endpoint(threadpool)에서 호출할 때 사용.
        루프가 준비되어 있으면 run_coroutine_threadsafe로 스케줄링.

        return:
          - True: 스케줄링 성공
          - False: 루프가 아직 없어서 못 보냄(WS 연결이 한 번도 없었거나, 아직 loop 저장 전)
        """
        with self._loop_lock:
            loop = self._loop

        if loop is None:
            return False

        asyncio.run_coroutine_threadsafe(self.publish(admin_id, message), loop)
        return True

    def publish_many_sync(self, admin_ids: Set[int], message: Dict[str, Any]) -> bool:
        with self._loop_lock:
            loop = self._loop
        if loop is None:
            return False
        asyncio.run_coroutine_threadsafe(self.publish_many(admin_ids, message), loop)
        return True

    # -------------------------
    # internal queueing
    # -------------------------
    def _enqueue(self, conn: WSConn, message: Dict[str, Any]) -> None:
        """
        느린 클라이언트 보호:
        - 큐가 꽉 차면 가장 오래된 1개 버리고 최신을 넣음
        """
        q = conn.send_q
        if q.full():
            try:
                q.get_nowait()
            except Exception:
                pass
        try:
            q.put_nowait(message)
        except Exception:
            # 그래도 실패하면 드랍
            return


# 전역 싱글톤
ws_manager = WSManager(queue_maxsize=200)
