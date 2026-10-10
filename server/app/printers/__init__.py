"""打印机连接管理:适配器工厂 + 每台打印机一条遥测循环 + 状态缓存。"""
from __future__ import annotations

import asyncio

from app.core.events import bus
from app.models import Printer
from app.printers.base import PrinterAdapter, PrinterError, Telemetry
from app.printers.creality_ws import CrealityWSAdapter
from app.printers.moonraker import MoonrakerAdapter

_REGISTRY: dict[str, type[PrinterAdapter]] = {
    MoonrakerAdapter.key: MoonrakerAdapter,
    CrealityWSAdapter.key: CrealityWSAdapter,
}


def adapter_keys() -> list[dict]:
    return [{"key": k, "name": v.name} for k, v in sorted(_REGISTRY.items())]


def build_adapter(printer: Printer) -> PrinterAdapter:
    cls = _REGISTRY.get(printer.adapter)
    if cls is None:
        raise PrinterError(f"未知适配器:{printer.adapter}")
    return cls(host=printer.host, port=printer.port,
               secret=printer.secret, settings=printer.settings or {})


class PrinterManager:
    """维护每台打印机的遥测循环,缓存最新状态,事件经 EventBus 推给前端。"""

    def __init__(self) -> None:
        self._tasks: dict[int, asyncio.Task] = {}
        self._latest: dict[int, Telemetry] = {}

    def latest(self, printer_id: int) -> dict | None:
        t = self._latest.get(printer_id)
        return t.to_dict() if t else None

    def stop(self, printer_id: int) -> None:
        task = self._tasks.pop(printer_id, None)
        if task:
            task.cancel()
        self._latest.pop(printer_id, None)

    async def shutdown(self) -> None:
        for pid in list(self._tasks):
            self.stop(pid)

    def ensure_loop(self, printer: Printer) -> None:
        if printer.id in self._tasks and not self._tasks[printer.id].done():
            return
        self._tasks[printer.id] = asyncio.create_task(self._loop(printer.id))

    async def _loop(self, printer_id: int) -> None:
        from app.core.db import SessionLocal
        while True:
            # 每轮从库里重读配置,支持热改地址/凭据
            async with SessionLocal() as db:
                printer = await db.get(Printer, printer_id)
            if printer is None or not printer.is_enabled:
                self.stop(printer_id)
                return
            adapter = build_adapter(printer)
            owner_id = printer.user_id
            try:
                async for tel in adapter.stream():
                    self._latest[printer_id] = tel
                    await bus.publish("printer_telemetry",
                                      {"printer_id": printer_id, **tel.to_dict()},
                                      user_id=owner_id)
                    if tel.state == "offline":
                        break
            except asyncio.CancelledError:
                raise
            except PrinterError:
                self._latest[printer_id] = Telemetry(state="offline")
                await bus.publish("printer_telemetry",
                                  {"printer_id": printer_id,
                                   "state": "offline"}, user_id=owner_id)
            finally:
                await adapter.aclose() if hasattr(adapter, "aclose") else None
            await asyncio.sleep(3.0)


manager = PrinterManager()
