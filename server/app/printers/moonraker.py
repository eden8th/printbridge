"""Klipper/Moonraker 适配器(Ender-3 V3 KE / Sonic Pad / ROOT 机 / 大量第三方机型)。

Moonraker REST API 文档完善:
  状态: GET  /printer/objects/query?print_stats&extruder&heater_bed&display_status
  上传: POST /server/files/upload  (multipart, root=gcodes)
  启动: POST /printer/print/start  {"filename": ...}
  控制: POST /printer/print/{pause|resume|cancel}
鉴权:X-Api-Key 头(未设 force_api_key 时可省略)。

CFS 料道状态(创想 K 系列):标准 Klipper/Moonraker 接口不暴露料道表。
优先级:Moonraker `box` 对象(API 直读,免凭证)→ SSH 只读读取
/mnt/UDISK/creality/userdata/box/material_box_info.json(需打印机开启 root 并配密码)。
实测颜色编码:0RRGGBB / #0RRGGBB(7位,首 0 为填充),解码取末 6 位。
"""
from __future__ import annotations

import asyncio
import json
import re
from pathlib import Path
from typing import AsyncIterator

import httpx

from app.printers.base import PrinterAdapter, PrinterError, Telemetry

_STATE_MAP = {
    "standby": "idle", "printing": "printing", "paused": "paused",
    "complete": "finished", "error": "error", "cancelled": "idle",
}

BOX_INFO_PATH = "/mnt/UDISK/creality/userdata/box/material_box_info.json"


def _decode_color(raw: str) -> str:
    """'#0fff014' / '0fff014' → '#fff014'(K2 的 7 位编码,首位 0 为填充);标准 6 位原样返回。"""
    c = str(raw or "").strip().lstrip("#")
    if re.fullmatch(r"0[0-9a-fA-F]{6}", c):
        return "#" + c[-6:].lower()
    if re.fullmatch(r"[0-9a-fA-F]{6}", c):
        return "#" + c.lower()
    return ""


def _ssh_read_box_info(host: str, password: str,
                       user: str = "root") -> dict | None:
    """SSH 只读读取料盒状态文件(禁止任何写操作)。"""
    import paramiko
    c = paramiko.SSHClient()
    c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    try:
        c.connect(host, username=user, password=password, timeout=6,
                  allow_agent=False, look_for_keys=False)
        _, out, _err = c.exec_command(f"cat {BOX_INFO_PATH}", timeout=8)
        data = out.read().decode("utf-8", "replace")
        return json.loads(data)
    finally:
        try:
            c.close()
        except Exception:
            pass


def _parse_box_object(box: dict) -> dict:
    """解析 Moonraker `box` 对象(创想 K 系列魔改固件暴露的 CFS 总状态)。

    结构:box.T1..T4 各为一个 CFS,每槽 color_value[i]/material_type[i];
    材质是 RFID 代码(001001=PLA、006005=PETG),名称映射取自 same_material
    ([code, color, [槽位], 材质名]),映射缺失时原样展示代码。"""
    mat_names: dict[str, str] = {}
    for row in box.get("same_material") or []:
        if isinstance(row, (list, tuple)) and len(row) >= 4:
            mat_names.setdefault(str(row[0]), str(row[3]))
    boxes = []
    for key in sorted(k for k, v in box.items()
                      if re.fullmatch(r"T\d", k) and isinstance(v, dict)):
        b = box[key]
        if str(b.get("type") or "") not in ("", "CFS"):
            continue
        colors = b.get("color_value") or []
        mats = b.get("material_type") or []
        slots = []
        for i, (c, m) in enumerate(zip(colors, mats), start=1):
            color = _decode_color(c)
            if not color:
                continue
            code = str(m or "").strip()
            slots.append({
                "index": i,
                "slot": f"{key}{'ABCD'[i - 1]}",
                "color": color,
                "material": mat_names.get(code, code),
                "name": mat_names.get(code, code),
                "brand": "",
                "temp_min": None,
                "temp_max": None,
                "rfid": any(x for x in (b.get("uuid") or [])),
            })
        if not slots:
            continue
        boxes.append({
            "box": key,
            "state": str(b.get("state") or ""),
            "type": str(b.get("type") or "CFS"),
            "temperature": b.get("temperature"),
            "humidity": b.get("dry_and_humidity"),
            "slots": slots,
        })
    connected = any(b["state"] == "connect" and b["slots"] for b in boxes)
    return {"available": True, "connected": connected, "boxes": boxes}


def _parse_box_info(data: dict) -> dict:
    boxes = []
    material = data.get("Material") or {}
    for box in material.get("info") or []:
        slots = []
        for i, s in enumerate(box.get("list") or [], start=1):
            if not isinstance(s, dict) or not s.get("name"):
                continue
            slots.append({
                "index": i,
                "slot": str(s.get("materialId") or i),
                "color": _decode_color(s.get("color")),
                "material": str(s.get("materialType") or ""),
                "name": str(s.get("name") or ""),
                "brand": str(s.get("brand") or ""),
                "temp_min": s.get("minTemp"),
                "temp_max": s.get("maxTemp"),
                "rfid": bool(s.get("rfid")),
            })
        boxes.append({
            "box": str(box.get("boxID") or ""),
            "state": str(box.get("state") or ""),
            "type": str(box.get("type") or ""),
            "temperature": box.get("temperature"),
            "humidity": box.get("dry_and_humidity"),
            "slots": slots,
        })
    connected = any(b["state"] == "connect" and b["slots"] for b in boxes)
    return {"available": True, "connected": connected, "boxes": boxes}


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
                "heater_bed": None, "display_status": None,
                "filament_rack": None})  # 创想 K 系列魔改:CFS 料架对象
        except httpx.HTTPError as exc:
            raise PrinterError(f"Moonraker 连接失败:{exc}") from exc
        if resp.status_code != 200:
            raise PrinterError(f"Moonraker 返回 {resp.status_code}")
        # 响应结构:{"result": {"status": {...}, "eventtime": ...}}
        data = resp.json().get("result", {}).get("status", {})
        ps = data.get("print_stats", {})
        disp = data.get("display_status", {})
        ext = data.get("extruder", {})
        bed = data.get("heater_bed", {})
        # filament_rack 存在即代表该固件具备 CFS 能力;color_value!="-1" 表示已装料
        rack = data.get("filament_rack")
        cfs = None
        if rack is not None:
            cfs = str(rack.get("color_value") or "-1") != "-1"
        return Telemetry(
            state=_STATE_MAP.get(str(ps.get("state")), "unknown"),
            nozzle_temp=_f(ext.get("temperature")), nozzle_target=_f(ext.get("target")),
            bed_temp=_f(bed.get("temperature")), bed_target=_f(bed.get("target")),
            progress=_f(disp.get("progress")),
            filename=str(ps.get("filename") or ""),
            message=str(ps.get("message") or ""),
            cfs_connected=cfs,
            raw=data,
        )

    async def select_slot(self, tnn: str) -> dict:
        """自动换料:执行 BOX_EXTRUDE_MATERIAL TNN=<盒子><料道>(如 T1C)。

        K2 内部 box_wrapper 模块的原生换料命令(实测验证,~20-60 秒):
        内部完成加热/退旧料/进新料/冲洗。注意:必须直发本命令并带 TNN
        参数——经 BOX_LOAD_MATERIAL 等宏间接调用会丢 TNN 导致内部错误。
        """
        import re as _re
        tnn = str(tnn or "").strip().upper()
        if not _re.fullmatch(r"T\d[A-D]", tnn):
            raise PrinterError(f"料道标识无效:{tnn}")
        try:
            resp = await self._client.post(
                "/printer/gcode/script",
                json={"script": f"BOX_EXTRUDE_MATERIAL TNN={tnn}"},
                timeout=httpx.Timeout(180.0))
        except httpx.HTTPError as exc:
            raise PrinterError(f"换料指令发送失败:{exc}") from exc
        if resp.status_code != 200:
            raise PrinterError(f"换料指令被拒绝({resp.status_code}):{resp.text[:200]}")
        return {"ok": True, "tnn": tnn}

    async def cfs_status(self) -> dict | None:
        """CFS 料道状态,按优先级:
        1. SSH 只读读取料盒文件(需配 SSH 密码):颜色/材质/品牌/产品名齐全,
           可精确匹配切片耗材档(如 Soleyin Basic PETG)
        2. Moonraker `box` 对象(API 直读,免凭证):颜色/材质类型,无产品名
        3. filament_rack 对象回退(仅 RFID 读取瞬间有值)。"""
        pwd = str(self.settings.get("ssh_password") or "")
        if pwd:
            try:
                data = await asyncio.to_thread(
                    _ssh_read_box_info, self.host, pwd)
                if data:
                    return _parse_box_info(data)
            except Exception:
                pass  # SSH 失败走免密通道
        try:
            resp = await self._client.get("/printer/objects/query?box")
            box = (resp.json().get("result", {}).get("status") or {}).get("box")
            if box:
                parsed = _parse_box_object(box)
                if parsed["boxes"]:
                    return parsed
        except (httpx.HTTPError, ValueError):
            pass  # 接口异常继续走回退
        try:
            resp = await self._client.get(
                "/printer/objects/query?filament_rack")
            rack = (resp.json().get("result", {}).get("status") or {}).get(
                "filament_rack")
        except (httpx.HTTPError, ValueError):
            return None
        if rack is None:
            return None
        color = str(rack.get("color_value") or "-1")
        material = str(rack.get("material_type") or "-1")
        loaded = color not in ("-1", "") and material not in ("-1", "")
        return {"available": True, "connected": loaded,
                "boxes": [], "raw": rack}

    async def ensure_ready(self, timeout: float = 90.0) -> str:
        """klippy 停机(如加热看门狗 key564 触发后的 shutdown)时自动恢复。

        Klipper 加热器故障会锁死到 shutdown,所有 G-code 均被拒绝,
        必须 FIRMWARE_RESTART。返回恢复后的状态(ready/shutdown/offline...)。
        """
        try:
            info = (await self._client.get("/printer/info")).json().get("result", {})
        except (httpx.HTTPError, ValueError):
            return "offline"
        if info.get("state") != "shutdown":
            return str(info.get("state") or "unknown")
        try:
            await self._client.post("/printer/firmware_restart")
        except httpx.HTTPError:
            pass
        waited = 0.0
        while waited < timeout:
            await asyncio.sleep(3.0)
            try:
                info = (await self._client.get("/printer/info")).json().get("result", {})
            except (httpx.HTTPError, ValueError):
                pass
            else:
                state = str(info.get("state") or "")
                if state == "ready":
                    return "ready"
                if state and state != "shutdown":
                    return state
            waited += 3.0
        return "shutdown"

    async def run_gcode(self, script: str) -> None:
        await self._command("/printer/gcode/script", {"script": script})

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
