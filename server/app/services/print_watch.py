"""打印结果跟踪:启动打印后轮询 Moonraker history,把最终状态与
诊断结论写回任务(moonraker history 的 status 由打印机固件判定)。
"""
from __future__ import annotations

import asyncio
import time

import httpx

from app.core.db import SessionLocal
from app.core.events import bus
from app.models import Job, Printer

_watchers: dict[int, asyncio.Task] = {}

DIAGNOSE = {
    "completed": "打印完成 ✔",
    "klippy_shutdown": ("Klipper 固件紧急关机导致打印中断——常见原因为喷头板串口"
                        "连接丢失或电源问题(本机历史故障多发生在打印开始后 15-20 "
                        "分钟),建议断电检查喷头排线,复发请凭日志联系创想售后"),
    "error": "Klipper 报错终止打印——具体原因见打印机日志(klippy.log),可把时间点发给我们排查",
    "cancelled": "打印被取消",
    "in_progress": "打印中",
}


def diagnose(status: str) -> str:
    return DIAGNOSE.get(status, f"未知打印状态:{status}")


def start_watcher(job_id: int, printer_id: int, remote_file: str) -> None:
    task = asyncio.create_task(_watch(job_id, printer_id, remote_file))
    _watchers[job_id] = task


def cancel_all() -> None:
    for t in _watchers.values():
        t.cancel()
    _watchers.clear()


async def _watch(job_id: int, printer_id: int, remote_file: str,
                 timeout_hours: float = 48.0) -> None:
    """每 30 秒查一次 history,直到该文件的任务结束(或超时放弃)。"""
    t_end = time.time() + timeout_hours * 3600
    async with httpx.AsyncClient(timeout=8) as client:
        while time.time() < t_end:
            await asyncio.sleep(30)
            try:
                async with SessionLocal() as db:
                    printer = await db.get(Printer, printer_id)
                    job = await db.get(Job, job_id)
                    if printer is None or job is None:
                        return
                    host, port = printer.host, printer.port or 7125
                r = await client.get(
                    f"http://{host}:{port}/server/history/list",
                    params={"limit": 30})
                entries = r.json().get("result", {}).get("jobs", [])
                entry = next((x for x in entries
                              if x.get("filename") == remote_file), None)
                if entry is None:
                    continue
                status = str(entry.get("status") or "")
                if status == "in_progress":
                    continue
                diagnosis = diagnose(status)
                async with SessionLocal() as db2:
                    j = await db2.get(Job, job_id)
                    if j is not None:
                        j.result = {**(j.result or {}),
                                    "print_status": status,
                                    "print_diagnosis": diagnosis}
                        await db2.commit()
                        await bus.publish("job_update", {
                            "id": job_id, "kind": j.kind, "state": j.state,
                            "detail": j.detail, "progress": j.progress,
                            "error": j.error, "result": j.result,
                        })
                return
            except asyncio.CancelledError:
                raise
            except Exception:
                continue  # 网络/查询失败,下个周期重试
