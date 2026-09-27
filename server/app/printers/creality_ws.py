"""创想三维 K 系列(K1/K1C/K1 Max/K2/Ender-3 V3)本地 WebSocket 适配器。

协议要点(社区逆向,Home Assistant 集成与 creality-k1-api 等项目同源):
  - 遥测: ws://<ip>:9999 ,打印机周期性推送大 JSON
  - 文件上传: FTP 21 端口(凭据可在打印机设置里覆盖)
  - 启动/暂停/恢复/停止: 通过同一条 WS 发 JSON 指令

各型号固件的指令 JSON 有差异,因此指令以「模板」形式存放在打印机
settings 里,可用探测工具(app.tools.probe_printer)对实机抓取后覆盖:
  ws_cmd_start   默认 {"print":{"command":"startprint","param":"{filename}"}}
  ws_cmd_pause   默认 {"print":{"command":"pause"}}
  ws_cmd_resume  默认 {"print":{"command":"resume"}}
  ws_cmd_stop    默认 {"print":{"command":"stop"}}
"""
from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import AsyncIterator

import aioftp
import websockets

from app.printers.base import PrinterAdapter, PrinterError, Telemetry

DEFAULT_PORT = 9999
FTP_PORT = 21


class CrealityWSAdapter(PrinterAdapter):
    key = "creality_ws"
    name = "创想三维 K 系列(本地 WebSocket)"

    # ---- 内部工具 ------------------------------------------------------
    def _ws_uri(self) -> str:
        port = self.port or DEFAULT_PORT
        return f"ws://{self.host}:{port}"

    async def _send_json(self, payload: dict) -> None:
        try:
            async with websockets.connect(self._ws_uri(), open_timeout=6) as ws:
                await ws.send(json.dumps(payload))
                try:  # 读取一条回执/推送即认为投递成功
                    await asyncio.wait_for(ws.recv(), timeout=3)
                except (asyncio.TimeoutError, websockets.ConnectionClosed):
                    pass
        except (OSError, websockets.WebSocketException) as exc:
            raise PrinterError(f"打印机 WebSocket 连接失败:{exc}") from exc

    # ---- 统一接口 ------------------------------------------------------
    async def status(self) -> Telemetry:
        """建立一次 WS 连接,取第一条遥测帧做归一化。"""
        try:
            async with websockets.connect(self._ws_uri(), open_timeout=6) as ws:
                raw = await asyncio.wait_for(ws.recv(), timeout=8)
        except (OSError, websockets.WebSocketException, asyncio.TimeoutError) as exc:
            raise PrinterError(f"打印机 WebSocket 连接失败:{exc}") from exc
        try:
            data = json.loads(raw)
        except ValueError as exc:
            raise PrinterError("遥测数据不是 JSON") from exc
        return normalize_telemetry(data)

    async def send_file(self, local_path: str, remote_name: str) -> str:
        ftp_port = int(self.settings.get("ftp_port") or FTP_PORT)
        user = str(self.settings.get("ftp_user") or "creality")
        passwd = str(self.settings.get("ftp_pass") or self.secret or "")
        remote_dir = str(self.settings.get("ftp_dir") or "/cache")
        try:
            async with aioftp.Client.context(self.host, ftp_port, user, passwd,
                                             timeout=15) as client:
                await client.upload(Path(local_path),
                                    destination=f"{remote_dir}/{remote_name}",
                                    write_into=False)
        except aioftp.errors.AIOFTPException as exc:
            raise PrinterError(
                f"FTP 上传失败:{exc}。请在打印机设置里核对 FTP 凭据/端口,"
                "或改用手动上传 G-code") from exc
        except OSError as exc:
            raise PrinterError(f"FTP 连接失败:{exc}") from exc
        return f"{remote_dir}/{remote_name}".lstrip("/")

    async def start_print(self, remote_name: str) -> None:
        name = Path(remote_name).name
        await self._send_json(_tpl(self.settings, "ws_cmd_start",
                                   {"print": {"command": "startprint",
                                              "param": "{filename}"}}, name))

    async def control(self, action: str) -> None:
        defaults = {
            "pause": {"print": {"command": "pause"}},
            "resume": {"print": {"command": "resume"}},
            "stop": {"print": {"command": "stop"}},
        }
        if action not in defaults:
            raise PrinterError(f"不支持的操作:{action}")
        await self._send_json(_tpl(self.settings, f"ws_cmd_{action}",
                                   defaults[action], ""))

    async def stream(self, interval: float = 1.0) -> AsyncIterator[Telemetry]:
        """长连接遥测循环:断线自动重连,每帧归一化后交给上层。"""
        keepalive = self.settings.get("ws_keepalive_json")  # 可选保活帧
        while True:
            try:
                async with websockets.connect(self._ws_uri(), open_timeout=6) as ws:
                    while True:
                        raw = await asyncio.wait_for(ws.recv(), timeout=30)
                        try:
                            data = json.loads(raw)
                        except ValueError:
                            continue
                        if isinstance(data, dict):
                            yield normalize_telemetry(data)
            except (OSError, websockets.WebSocketException, asyncio.TimeoutError):
                yield Telemetry(state="offline")
                await asyncio.sleep(max(interval, 3.0))


# ---- 归一化:不同固件字段名有差异,按常见命名递归找值 ---------------------
def _find_first(obj, keys: tuple[str, ...], depth: int = 0):
    if depth > 4:
        return None
    if isinstance(obj, dict):
        for k in keys:
            if k in obj and obj[k] not in (None, ""):
                return obj[k]
        for v in obj.values():
            found = _find_first(v, keys, depth + 1)
            if found is not None:
                return found
    elif isinstance(obj, list):
        for v in obj:
            found = _find_first(v, keys, depth + 1)
            if found is not None:
                return found
    return None


def normalize_telemetry(data: dict) -> Telemetry:
    """字段名以 K2 Pro 实机帧为准(2026-09 对 192.168.8.220 实测校准),
    同时保留 K1 系列社区已知的旧字段名兜底。"""
    state_raw = data.get("state") if isinstance(data.get("state"), (int, float)) else \
        str(_find_first(data, ("status", "machineStatus")) or "").lower()
    # K 系列 state 枚举(实测:打印完成时为 2;0=待机,1=打印中 为社区通用值)
    if isinstance(state_raw, (int, float)):
        state = {0: "idle", 1: "printing", 2: "finished", 3: "paused"}.get(
            int(state_raw), "unknown")
    else:
        state = ("printing" if state_raw in ("printing", "print", "working")
                 else "paused" if "pause" in state_raw
                 else "finished" if state_raw in ("complete", "completed", "finish", "done")
                 else "error" if state_raw in ("error", "failed", "abort")
                 else "idle" if state_raw in ("idle", "standby", "ready", "free")
                 else state_raw if state_raw in ("offline", "unknown") else "unknown")
    prog = _find_first(data, ("printProgress", "progress", "percent"))
    try:
        prog = float(prog)
        if prog > 1.0:
            prog /= 100.0
    except (TypeError, ValueError):
        prog = None

    def temp(*keys: str) -> float | None:
        v = _find_first(data, keys)
        try:
            return round(float(v), 1) if v is not None else None
        except (TypeError, ValueError):
            return None

    filename_full = str(_find_first(data, ("printFileName", "filename", "gcode_filename")) or "")
    filename = filename_full.rsplit("/", 1)[-1] if filename_full else ""
    remaining = _find_first(data, ("printLeftTime", "remaining_time"))
    try:
        remaining = float(remaining) if remaining is not None else None
    except (TypeError, ValueError):
        remaining = None

    cfs = data.get("cfsConnect")
    return Telemetry(
        state=state,
        nozzle_temp=temp("nozzleTemp", "cur_nozzle_temp", "temp_of_nozzle"),
        nozzle_target=temp("targetNozzleTemp", "dest_nozzle_temp", "nozzleTargetTemp"),
        bed_temp=temp("bedTemp0", "cur_heatbed_temp", "temp_of_heatbed"),
        bed_target=temp("targetBedTemp0", "dest_heatbed_temp", "bedTargetTemp"),
        chamber_temp=temp("boxTemp", "cur_chamber_temp", "chamberTemp"),
        chamber_target=temp("targetBoxTemp", "target_chamber_temp"),
        progress=prog,
        filename=filename,
        remaining_sec=remaining,
        layer=str(_find_first(data, ("layer", "curLayer")) or ""),
        cfs_connected=bool(cfs) if cfs is not None else None,
        message=str(_find_first(data, ("message", "err_msg")) or ""),
        raw=data,
    )


def _tpl(settings: dict, key: str, default: dict, filename: str) -> dict:
    """从 settings 取指令模板并替换 {filename};模板允许存成 dict 或 JSON 字符串。"""
    raw = settings.get(key, default)
    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except ValueError:
            raw = default
    text = json.dumps(raw).replace("{filename}", filename)
    return json.loads(text)
