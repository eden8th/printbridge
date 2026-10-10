"""进程内事件总线:任务进度/打印机遥测推送,广播给全部订阅者。"""
import asyncio
import json
from typing import Any


class EventBus:
    def __init__(self) -> None:
        self._queues: set[asyncio.Queue] = set()
        self._lock = asyncio.Lock()

    async def subscribe(self) -> asyncio.Queue:
        q: asyncio.Queue = asyncio.Queue(maxsize=512)
        async with self._lock:
            self._queues.add(q)
        return q

    async def unsubscribe(self, q: asyncio.Queue) -> None:
        async with self._lock:
            self._queues.discard(q)

    async def publish(self, event_type: str, data: dict[str, Any],
                      user_id: int | None = None) -> None:
        # user_id 参数保留在签名里以兼容现有调用点,单用户形态下不做过滤
        payload = json.dumps({"type": event_type, "data": data}, ensure_ascii=False)
        for q in list(self._queues):
            try:
                q.put_nowait(payload)
            except asyncio.QueueFull:
                pass  # 客户端消费太慢则丢帧,遥测场景可接受


bus = EventBus()