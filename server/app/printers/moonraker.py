"""Klipper/Moonraker 适配器(Ender-3 V3 KE / Sonic Pad / ROOT 机 / 大量第三方机型)。

Moonraker REST API 文档完善:
  状态: GET  /printer/objects/query?print_stats&extruder&heater_bed&display_status
  上传: POST /server/files/upload  (multipart, root=gcodes)
  启动: POST /printer/print/start  {"filename": ...}
  控制: POST /printer/print/{pause|resume|cancel}
鉴权:X-Api-Key 头(未设 force_api_key 时可省略)。
"""
from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import AsyncIterator

import httpx

from app.printers.base import PrinterAdapter, PrinterError, Telemetry

_STATE_MAP = {
    "standby": "idle", "printing": "printing", "paused": "paused",
    "complete": "finished", "error": "error", "cancelled": "idle",
}


class MoonrakerAdapter(PrinterAdapter):
    key = "moonraker"
    name = "Klipper / Moonraker"

    def __init__(self, host: str, port: int | None = None, secret: str = "",
                 settings: dict | None = None) -> None:
        super().__init__(host, port or 7125, secret, settings)
        self._client = httpx.AsyncClient(
            base_url=f"http://{self.host}:{self.port}",
            timeout=httpx.Timeout(8.0),
            headers={"X-Api-Key": self.secret} if self.secret else {},
        )

    async def aclose(self) -> None:
        await self._client.aclose()

    async def status(self) -> Telemetry:
        try:
            resp = await self._client.get("/printer/objects/query", params={
                "print_stats": None, "extruder": None,
                "heater_bed": None, "display_status": None})
        except httpx.HTTPError as exc:
            raise PrinterError(f"Moonraker 连接失败:{exc}") from exc
        if resp.status_code != 200:
            raise PrinterError(f"Moonraker 返回 {resp.status_code}")
        data = resp.json().get("status", {})
        ps = data.get("print_stats", {})
        disp = data.get("display_status", {})
        ext = data.get("extruder", {})
        bed = data.get("heater_bed", {})
        return Telemetry(
            state=_STATE_MAP.get(str(ps.get("state")), "unknown"),
            nozzle_temp=_f(ext.get("temperature")), nozzle_target=_f(ext.get("target")),
            bed_temp=_f(bed.get("temperature")), bed_target=_f(bed.get("target")),
            progress=_f(disp.get("progress")),
            filename=str(ps.get("filename") or ""),
            message=str(ps.get("message") or ""),
            raw=data,
        )

    async def send_file(self, local_path: str, remote_name: str) -> str:
        p = Path(local_path)
        try:
            resp = await self._client.post("/server/files/upload",
                                           files={"file": (remote_name, p.read_bytes())},
                                           data={"root": "gcodes", "print": "false"})
        except httpx.HTTPError as exc:
            raise PrinterError(f"上传失败:{exc}") from exc
        if resp.status_code != 201:
            raise PrinterError(f"上传被拒绝({resp.status_code}):{resp.text[:200]}")
        return str(resp.json().get("result", {}).get("item", {}).get("path", remote_name))

    async def _command(self, path: str, payload: dict | None = None) -> None:
        try:
            resp = await self._client.post(path, json=payload or {})
        except httpx.HTTPError as exc:
            raise PrinterError(f"指令发送失败:{exc}") from exc
        if resp.status_code != 200:
            raise PrinterError(f"指令被拒绝({resp.status_code}):{resp.text[:200]}")

    async def start_print(self, remote_name: str) -> None:
        await self._command("/printer/print/start", {"filename": remote_name})

    async def control(self, action: str) -> None:
        mapping = {"pause": "pause", "resume": "resume", "stop": "cancel"}
        if action not in mapping:
            raise PrinterError(f"不支持的操作:{action}")
        await self._command(f"/printer/print/{mapping[action]}")

    async def stream(self, interval: float = 2.0) -> AsyncIterator[Telemetry]:
        """P0 用轮询实现遥测流;P1 切换到 Moonraker websocket(JSON-RPC)。"""
        while True:
            try:
                yield await self.status()
            except PrinterError:
                yield Telemetry(state="offline")
            await asyncio.sleep(interval)


def _f(v) -> float | None:
    try:
        return round(float(v), 1) if v is not None else None
    except (TypeError, ValueError):
        return None
