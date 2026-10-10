"""实时事件通道:任务进度 + 打印机遥测,单一 WS 连接推送全部事件。

自托管单用户:匿名连接,收全部事件(服务只监听内网,没有跨用户概念)。
"""
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