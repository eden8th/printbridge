"""打印机协议探测工具(只读,绝不触发打印)。

用法:
  python -m app.tools.probe_printer --host 192.168.1.50 [--adapter creality_ws|moonraker]

creality_ws 模式:抓取 WebSocket 首帧遥测原文(字段名诊断用)、测试 FTP 登录;
moonraker 模式:测试对象查询与文件列表。输出可直接粘贴给适配器设置覆盖。
"""
from __future__ import annotations

import argparse
import asyncio
import json

from app.printers.creality_ws import FTP_PORT, normalize_telemetry
from app.printers.moonraker import MoonrakerAdapter


async def probe_creality(host: str, port: int, seconds: float) -> None:
    import websockets

    uri = f"ws://{host}:{port}"
    print(f"[*] 连接 {uri} (等待 {seconds:.0f}s 抓取遥测帧)")
    try:
        async with websockets.connect(uri, open_timeout=6) as ws:
            end = asyncio.get_event_loop().time() + seconds
            n = 0
            while asyncio.get_event_loop().time() < end:
                try:
                    raw = await asyncio.wait_for(ws.recv(), timeout=3)
                except (asyncio.TimeoutError, Exception) as exc:  # noqa: BLE001
                    print(f"    recv: {exc!r}")
                    break
                n += 1
                try:
                    data = json.loads(raw)
                except ValueError:
                    print(f"[帧 {n}] 非 JSON: {raw[:120]}")
                    continue
                if n == 1:
                    print(f"[帧 1 原文] {json.dumps(data, ensure_ascii=False)[:1500]}")
                    tel = normalize_telemetry(data)
                    print(f"[归一化] {tel.to_dict()}")
                if n == 1:
                    print("[后续帧省略,Ctrl+C 可中断]")
        print(f"[*] 共收到 {n} 帧")
    except Exception as exc:  # noqa: BLE001
        print(f"[!] WS 失败:{exc!r}")
        print("    -> 尝试常见端口 80/8080/9999/7125 ...")
        for p in (80, 8080, 9999, 7125):
            try:
                _, w = await asyncio.open_connection(host, p)
                w.close()
                print(f"    端口 {p} 开放")
            except OSError:
                print(f"    端口 {p} 不通")

    print(f"\n[*] FTP 上传通道探测(端口 {FTP_PORT},只 LIST 不上传)")
    import aioftp
    for user, passwd in (("creality", ""), ("anonymous", "anonymous")):
        try:
            async with aioftp.Client.context(host, FTP_PORT, user, passwd,
                                             timeout=8) as client:
                listing = [p.name for p, _f in await client.list()]  # type: ignore[misc]
                print(f"[OK] 凭据 {user}/{passwd or '(空)'} 可登录,根目录:"
                      f" {listing[:10]}")
                return
        except Exception as exc:  # noqa: BLE001
            print(f"[--] {user} 登录失败:{exc!r}")


async def probe_moonraker(host: str, port: int, secret: str) -> None:
    import httpx
    headers = {"X-Api-Key": secret} if secret else {}
    async with httpx.AsyncClient(
            base_url=f"http://{host}:{port}", timeout=8, headers=headers) as c:
        for path in ("/server/info", "/printer/objects/query?print_stats&extruder&heater_bed",
                     "/server/files/list?root=gcodes"):
            r = await c.get(path)
            print(f"[{r.status_code}] {path} -> {r.text[:300]}")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--host", required=True)
    ap.add_argument("--adapter", default="creality_ws",
                    choices=["creality_ws", "moonraker"])
    ap.add_argument("--port", type=int, default=0)
    ap.add_argument("--secret", default="")
    ap.add_argument("--seconds", type=float, default=10)
    args = ap.parse_args()
    if args.adapter == "moonraker":
        asyncio.run(probe_moonraker(args.host, args.port or 7125, args.secret))
    else:
        asyncio.run(probe_creality(args.host, args.port or 9999, args.seconds))


if __name__ == "__main__":
    main()
