# app/endpoints/websocket.py
from __future__ import annotations

import asyncio
from typing import Any

from fastapi import APIRouter, WebSocket, WebSocketDisconnect, Query

from service.ws_manager import ws_manager, WSConn

router = APIRouter(prefix="/ws", tags=["WebSocket"])


@router.websocket("/notifications")
async def notifications_ws(
    websocket: WebSocket,
    admin_id: int = Query(..., description="admin_user.id (대표관리자=0)"),
) -> None:
    """
    연결:
      ws://{host}/ws/notifications?admin_id=0

    서버 → 클라 메시지 예시:
      {"type":"notification_created", "notification": {...}, "unread_count": 3}
      {"type":"notification_read", "notification_id": 10, "unread_count": 2}
      {"type":"unread_count", "unread_count": 5}

    클라 → 서버(선택):
      {"type":"ping"}  -> {"type":"pong"}
    """
    conn: WSConn = await ws_manager.register(admin_id, websocket)

    try:
        while True:
            recv_task = asyncio.create_task(websocket.receive_json())
            send_task = asyncio.create_task(conn.send_q.get())

            done, pending = await asyncio.wait(
                {recv_task, send_task},
                return_when=asyncio.FIRST_COMPLETED,
            )

            for t in pending:
                t.cancel()

            if send_task in done:
                msg = send_task.result()
                await websocket.send_json(msg)

            if recv_task in done:
                data = recv_task.result() or {}
                t = str(data.get("type") or "")

                if t == "ping":
                    # ping/pong은 즉시 응답(큐를 안 거침)
                    await websocket.send_json({"type": "pong"})
                # 필요 시 확장:
                # - WS 기반 mark_read 요청을 받고 서버에서 처리하고 publish 하는 구조도 가능
                # - 지금은 REST로 mark_read 하기로 했으니 noop

    except WebSocketDisconnect:
        pass
    except Exception:
        pass
    finally:
        await ws_manager.unregister(admin_id, conn)
