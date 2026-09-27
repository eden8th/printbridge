"""实时事件通道:任务进度 + 打印机遥测,单一 WS 连接推送全部事件。"""
from __future__ import annotations

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from app.core.events import bus

router = APIRouter()


@router.websocket("/ws/events")
async def events(ws: WebSocket) -> None:
    await ws.accept()
    q = await bus.subscribe()
    try:
        while True:
            payload = await q.get()
            await ws.send_text(payload)
    except WebSocketDisconnect:
        pass
    finally:
        await bus.unsubscribe(q)
