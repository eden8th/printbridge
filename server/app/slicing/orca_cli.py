"""切片引擎:封装 OrcaSlicer / Creality Print 的无头 CLI。

两者都是 Orca(Slic3r 系)分支,核心调用形态一致:
  <exe> --slice <in.3mf> [--plate N] \
        --load-settings <machine.json> \
        --load-filaments <filament.json,...> \
        --load-process <process.json> \
        --export-gcode -o <out.gcode>

不同版本 CLI 参数可能微调,因此在设置页可覆盖命令模板;`--version`
探测与 --help 输出保存,便于诊断。引擎路径按 优先级 自动探测:
设置值 > 环境常见安装位置 > PATH。
"""
from __future__ import annotations

import asyncio
import json
import os
import re
import shutil
import subprocess  # noqa: S404 - 固定白名单参数,不接受用户拼接
import sys
from dataclasses import dataclass, field
from pathlib import Path

_WIN_COMMON = [
    r"D:\Creality\Creality Print 7.1\CrealityPrint.exe",
    r"D:\Creality\Creality Print\CrealityPrint.exe",
    r"C:\Program Files\Creality Print\CrealityPrint.exe",
    r"C:\Program Files\OrcaSlicer\orca-slicer.exe",
    r"C:\Program Files\OrcaSlicer\orca-slicer-console.exe",
]


@dataclass
class SliceRequest:
    input_path: str
    output_gcode: str
    machine_files: list[str]
    filament_files: list[str]
    process_file: str
    plate: int | None = None   # 3MF 多板时从 1 开始;None=跟随文件默认板
    log_path: str = ""


@dataclass
class SliceResult:
    ok: bool
    gcode_path: str = ""
    duration_sec: float = 0.0
    estimated_sec: float = 0.0     # G-code 头注释里的预估打印时长
    filament_grams: float = 0.0    # 预估耗材克重
    error: str = ""
    log_tail: list[str] = field(default_factory=list)


def detect_slicer(configured: str = "") -> str:
    """定位切片器可执行文件。"""
    if configured and Path(configured).is_file():
        return configured
    for cand in _WIN_COMMON:
        if Path(cand).is_file():
            return cand
    found = shutil.which("orca-slicer") or shutil.which("CrealityPrint")
    return found or ""


async def slice_model(req: SliceRequest, exe_path: str = "") -> SliceResult:
    exe = detect_slicer(exe_path)
    if not exe:
        return SliceResult(ok=False, error=(
            "未找到切片器。请在设置页指定 OrcaSlicer / Creality Print 的安装路径"))

    argv = [
        exe, "--slice", req.input_path,
        "--load-settings", ",".join(req.machine_files),
        "--load-filaments", ",".join(req.filament_files),
        "--load-process", req.process_file,
        "--export-gcode", "-o", req.output_gcode,
    ]
    if req.plate:
        argv += ["--plate", str(req.plate)]
    if req.log_path:
        Path(req.log_path).parent.mkdir(parents=True, exist_ok=True)

    import time
    t0 = time.monotonic()
    flags = getattr(subprocess, "CREATE_NO_WINDOW", 0) if sys.platform == "win32" else 0
    try:
        proc = await asyncio.create_subprocess_exec(
            *argv,
            stdout=asyncio.subprocess.PIPE if req.log_path else subprocess.DEVNULL,
            stderr=asyncio.subprocess.STDOUT if req.log_path else subprocess.DEVNULL,
            creationflags=flags,
        )
        tail: list[str] = []
        if req.log_path and proc.stdout is not None:
            logf = open(req.log_path, "wb")  # noqa: SIM115 - 随进程生命周期关闭
            try:
                async for line in proc.stdout:
                    tail.append(line.decode("utf-8", "replace").rstrip())
                    if len(tail) > 200:
                        tail = tail[-200:]
                    logf.write(line)
            finally:
                logf.close()
        else:
            await proc.wait()
        code = await proc.wait()
    except FileNotFoundError:
        return SliceResult(ok=False, error=f"切片器不可执行:{exe}")
    duration = time.monotonic() - t0

    if code != 0 or not Path(req.output_gcode).is_file():
        return SliceResult(ok=False, duration_sec=duration,
                           error=f"切片失败(退出码 {code})",
                           log_tail=tail if req.log_path else [])
    est, grams = parse_gcode_stats(req.output_gcode)
    return SliceResult(ok=True, gcode_path=req.output_gcode, duration_sec=round(duration, 1),
                       estimated_sec=est, filament_grams=grams,
                       log_tail=tail if req.log_path else [])


_TIME_RE = re.compile(r";\s*(?:estimated\s+)?model printing time:\s*"
                      r"(?:(\d+)h)?\s*(?:(\d+)m)?\s*(?:(\d+)s)?", re.I)
_G_RE = re.compile(r";\s*total filament used.*?([\d.]+)\s*g", re.I)


def parse_gcode_stats(gcode_path: str) -> tuple[float, float]:
    """从 Orca 系 G-code 头注释提取预估时长与耗材克重。解析不出返回 (0,0)。"""
    try:
        with open(gcode_path, "r", encoding="utf-8", errors="replace") as fh:
            head = "".join(fh.readline() for _ in range(400))
    except OSError:
        return 0.0, 0.0
    seconds = 0.0
    m = _TIME_RE.search(head)
    if m:
        h, mi, s = (int(x or 0) for x in m.groups())
        seconds = h * 3600 + mi * 60 + s
    grams = 0.0
    m = _G_RE.search(head)
    if m:
        grams = float(m.group(1))
    return seconds, grams


def detect_from_settings(cfg: dict) -> str:
    """settings 服务里的 slicer 配置 -> 引擎路径。"""
    return detect_slicer(str(cfg.get("exe_path") or ""))
