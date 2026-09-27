"""局域网打印机自动发现。

原理:并行 TCP 探测网段内的适配器特征端口(创想 K 系列 9999 / Moonraker 7125),
对开放端口做协议级识别:
  - 7125 → GET /printer/info、/server/info(Klipper 主机名、固件版本)
  - 9999 → WebSocket 读取第一帧遥测(创想 K 系列),从原始 JSON 里提取机型名

只读探测,绝不发送打印指令。网段来源:优先用户指定 CIDR,否则自动枚举
本机所有私网网段的 /24(过滤 fake-ip 198.18.0.0/15、回环、链路本地)。
"""
from __future__ import annotations

import asyncio
import ipaddress
import json
import re
import socket
import time

import httpx
import websockets

DEFAULT_PORTS: dict[int, str] = {9999: "creality_ws", 7125: "moonraker"}
_TCP_TIMEOUT = 0.4          # 单端口连通判定
_PROBE_TIMEOUT = 5.0        # 协议识别总预算
_CONCURRENCY = 128
_EXCLUDED_NETS = [
    ipaddress.ip_network("198.18.0.0/15"),   # Clash fake-ip 等 TUN 虚拟段
    ipaddress.ip_network("169.254.0.0/16"),  # 链路本地
]


def _is_private_real(ip: str) -> bool:
    try:
        addr = ipaddress.ip_address(ip)
    except ValueError:
        return False
    if not addr.is_private or addr.is_loopback or addr.is_link_local:
        return False
    return not any(addr in net for net in _EXCLUDED_NETS)


def candidate_subnets() -> list[str]:
    """枚举本机所在私网 /24 网段。"""
    ips: set[str] = set()
    # 策略1:UDP connect 拿默认路由出口地址(不发任何包)
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            s.connect(("223.5.5.5", 53))
            ips.add(s.getsockname()[0])
        finally:
            s.close()
    except OSError:
        pass
    # 策略2:主机名解析出的全部本机地址(覆盖多网卡)
    try:
        for info in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET):
            ips.add(info[4][0])
    except OSError:
        pass
    subnets: set[str] = set()
    for ip in ips:
        if _is_private_real(ip):
            subnets.add(str(ipaddress.ip_network(f"{ip}/24", strict=False)))
    return sorted(subnets)


async def _tcp_open(host: str, port: int, sem: asyncio.Semaphore) -> tuple[str, int] | None:
    async with sem:
        try:
            _, writer = await asyncio.wait_for(
                asyncio.open_connection(host, port), _TCP_TIMEOUT)
            writer.close()
            try:
                await writer.wait_closed()
            except OSError:
                pass
            return host, port
        except (OSError, asyncio.TimeoutError):
            return None


def _extract_name_hint(data: dict) -> str:
    """从创想遥测 JSON 里递归找机型/设备名字段。"""
    keys = ("machineType", "machineName", "printerName", "deviceName",
            "printer_model", "modelName", "printerModel", "machine_model")
    found: list[str] = []

    def walk(node, depth: int = 0) -> None:
        if depth > 5 or len(found) >= 3:
            return
        if isinstance(node, dict):
            for k, v in node.items():
                if k in keys and isinstance(v, str) and 0 < len(v) <= 60:
                    found.append(v.strip())
                elif isinstance(v, (dict, list)):
                    walk(v, depth + 1)
        elif isinstance(node, list):
            for v in node:
                walk(v, depth + 1)

    walk(data)
    return found[0] if found else ""


async def _probe_creality(host: str, port: int) -> dict | None:
    try:
        async with websockets.connect(f"ws://{host}:{port}",
                                      open_timeout=_PROBE_TIMEOUT) as ws:
            raw = await asyncio.wait_for(ws.recv(), _PROBE_TIMEOUT)
    except (OSError, asyncio.TimeoutError, websockets.WebSocketException):
        return None
    try:
        data = json.loads(raw)
    except ValueError:
        data = {}
    name = _extract_name_hint(data) if isinstance(data, dict) else ""
    return {"host": host, "adapter": "creality_ws", "port": port,
            "name": name or "创想设备", "detail": {
                "first_frame": (raw[:300] if isinstance(raw, str) else str(raw)[:300]),
            }}


def _match_bundle_key(text: str) -> str | None:
    """按发现到的名字/主机名模糊匹配已知机型参数包(K2Pro-29BB → creality_k2pro)。"""
    from app.slicing.registry import list_bundles
    norm = re.sub(r"[^a-z0-9]", "", (text or "").lower())
    if not norm:
        return None
    for b in list_bundles():
        bn = re.sub(r"[^a-z0-9]", "", b.name.lower())   # "Creality K2 Pro" -> crealityk2pro
        short = bn.replace("creality", "")
        if short and short in norm:
            return b.key
    return None


async def _probe_moonraker(host: str, port: int) -> dict | None:
    try:
        async with httpx.AsyncClient(timeout=_PROBE_TIMEOUT) as client:
            info = {}
            try:
                r = await client.get(f"http://{host}:{port}/printer/info")
                if r.status_code == 200:
                    info = r.json().get("result", {})
            except httpx.HTTPError:
                pass
            if not info:
                return None
            hostname = str(info.get("hostname") or "")
            version = str(info.get("software_version") or "")
            return {"host": host, "adapter": "moonraker", "port": port,
                    "name": f"Klipper · {hostname or host}", "detail": {
                        "hostname": hostname,
                        "software_version": version,
                        "model": _match_bundle_key(hostname),
                    }}
    except (OSError, httpx.HTTPError):
        return None


async def discover(cidr: str | None = None) -> dict:
    """扫描网段并识别打印机。返回 {scanned, duration_sec, candidates}。"""
    t0 = time.monotonic()
    if cidr:
        try:
            net = ipaddress.ip_network(cidr, strict=False)
        except ValueError as exc:
            raise ValueError(f"网段格式无效:{cidr}") from exc
        subnets = [str(net)]
    else:
        subnets = candidate_subnets()
    if not subnets:
        return {"scanned": [], "duration_sec": 0.0, "candidates": [],
                "hint": "未识别到本机私网网段,请手动填写网段"}

    sem = asyncio.Semaphore(_CONCURRENCY)
    tasks = []
    for subnet in subnets:
        for host in ipaddress.ip_network(subnet).hosts():
            for port in DEFAULT_PORTS:
                tasks.append(_tcp_open(str(host), port, sem))
    results = await asyncio.gather(*tasks)
    hits = [r for r in results if r]

    # 同主机同端口去重后做协议识别
    probe_tasks = []
    for host, port in set(hits):
        adapter = DEFAULT_PORTS[port]
        probe_tasks.append(_probe_creality(host, port) if adapter == "creality_ws"
                           else _probe_moonraker(host, port))
    probed = await asyncio.gather(*probe_tasks)
    candidates = [p for p in probed if p]
    # 同主机同时开放 7125(Moonraker 标准协议)+ 9999(创想 WS)时,
    # 只保留 Moonraker 协议的候选,并注明本地 WS 也可用
    by_host: dict[str, list[dict]] = {}
    for c in candidates:
        by_host.setdefault(c["host"], []).append(c)
    merged: list[dict] = []
    for host, group in by_host.items():
        group.sort(key=lambda c: 0 if c["adapter"] == "moonraker" else 1)
        best = group[0]
        if len(group) > 1:
            best = {**best, "detail": {
                **best["detail"],
                "alt_adapters": [g["adapter"] for g in group[1:]],
            }}
        merged.append(best)
    merged.sort(key=lambda c: c["name"])
    return {"scanned": subnets, "duration_sec": round(time.monotonic() - t0, 1),
            "candidates": merged}
