"""切片引擎:封装 OrcaSlicer 的无头 CLI(开源,完整支持无头切片)。

实测确认的调用形态(Orca v2.4.2):--slice 是板号整数,产物是内含
G-code 的 3MF 容器(--export-3mf),由本模块解包出裸 .gcode:
  orca-slicer --load-settings <machine.json> \
      --load-settings <process.json> \
      --load-filaments <filament.json> \
      --slice 0 --export-3mf <out.gcode.3mf> <input.3mf>

注意:Creality Print 7.x 经二进制验证已移除无头 CLI(报
"Invalid value for option --slice" 且空输出退出),不再作为引擎;
--slice 不配 --export-3mf 时 Orca 会误入 GUI 模式挂起,两者必须成对。
"""
from __future__ import annotations

import asyncio
import re
import shutil
import subprocess  # noqa: S404 - 固定白名单参数,不接受用户拼接
import sys
import time
import zipfile
from dataclasses import dataclass, field
from pathlib import Path

_WIN_COMMON = [
    r"E:\Project\printbridge\tools\orca\orca-slicer.exe",
    r"C:\Program Files\OrcaSlicer\orca-slicer.exe",
    r"C:\Program Files\OrcaSlicer\orca-slicer-console.exe",
]


@dataclass
class SliceRequest:
    input_path: str
    output_dir: str             # Orca 把产物写入该目录(--outputdir)
    machine_files: list[str]
    filament_files: list[str]
    process_file: str
    plate: int = 0              # 0=全部板;单板 3MF 常见
    log_path: str = ""


@dataclass
class SliceResult:
    ok: bool
    gcode_path: str = ""
    thumbnail_path: str = ""       # 切片板预览图(从产物容器提取)
    duration_sec: float = 0.0
    estimated_sec: float = 0.0     # G-code 头注释里的预估打印时长
    filament_grams: float = 0.0    # 预估耗材克重
    error: str = ""
    log_tail: list[str] = field(default_factory=list)


def detect_slicer(configured: str = "") -> str:
    """定位 OrcaSlicer 可执行文件。"""
    if configured and Path(configured).is_file():
        return configured
    for cand in _WIN_COMMON:
        if Path(cand).is_file():
            return cand
    import shutil
    found = shutil.which("orca-slicer") or shutil.which("orca-slicer-console")
    return found or ""


def _run_sync(req: SliceRequest, exe: str) -> tuple[int, list[str]]:
    """同步运行切片子进程(Windows 上 asyncio 管道对 GUI 子系统程序不可靠)。"""
    out_dir = Path(req.output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    argv = [exe]
    for m in req.machine_files:
        argv += ["--load-settings", m]
    argv += ["--load-settings", req.process_file]
    for f in req.filament_files:
        argv += ["--load-filaments", f]
    argv += ["--slice", str(req.plate or 0),
             "--export-3mf", str(out_dir / "result.gcode.3mf"),
             req.input_path]

    tail: list[str] = []
    logf = open(req.log_path, "wb") if req.log_path else None  # noqa: SIM115
    flags = getattr(subprocess, "CREATE_NO_WINDOW", 0) if sys.platform == "win32" else 0
    try:
        proc = subprocess.Popen(
            argv, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            creationflags=flags)
    except FileNotFoundError:
        return -1, [f"切片器不可执行:{exe}"]
    try:
        assert proc.stdout is not None
        for raw in proc.stdout:
            line = raw.decode("utf-8", "replace").rstrip()
            tail.append(line)
            if len(tail) > 400:
                tail = tail[-400:]
            if logf:
                logf.write(raw)
        code = proc.wait()
    finally:
        if logf:
            logf.close()
        if proc.poll() is None:
            proc.kill()
    return code, tail


def _extract_gcode(gcode_3mf: Path, out_dir: Path) -> tuple[str, str]:
    """从 .gcode.3mf 容器解出最大的 plate_N.gcode 与板预览图。"""
    with zipfile.ZipFile(gcode_3mf) as z:
        members = [i for i in z.infolist()
                   if re.fullmatch(r"Metadata/plate_\d+\.gcode", i.filename)
                   and i.file_size > 0]
        if not members:
            return "", ""
        best = max(members, key=lambda i: i.file_size)
        target = out_dir / Path(best.filename).name
        with z.open(best) as src, open(target, "wb") as dst:
            shutil.copyfileobj(src, dst)
        # 板预览图:优先 Metadata/plate_N.png,退而取缩略图
        thumb = ""
        pngs = [i for i in z.infolist()
                if re.fullmatch(r"Metadata/plate_\d+\.png", i.filename)]
        if not pngs:
            pngs = [i for i in z.infolist()
                    if i.filename.startswith("Auxiliaries/.thumbnails/")
                    and i.filename.endswith(".png")]
        if pngs:
            png = max(pngs, key=lambda i: i.file_size)
            thumb_target = out_dir / "plate_thumb.png"
            with z.open(png) as src, open(thumb_target, "wb") as dst:
                shutil.copyfileobj(src, dst)
            thumb = str(thumb_target)
        return str(target), thumb


async def slice_model(req: SliceRequest, exe_path: str = "") -> SliceResult:
    exe = detect_slicer(exe_path)
    if not exe:
        return SliceResult(ok=False, error=(
            "未找到 OrcaSlicer。请把便携版解压到项目 tools/orca/,"
            "或在设置页指定安装路径"))

    out_dir = Path(req.output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    t0 = time.monotonic()
    try:
        code, tail = await asyncio.to_thread(_run_sync, req, exe)
    except Exception as exc:  # noqa: BLE001
        return SliceResult(ok=False, error=f"切片进程异常:{exc!r}")
    duration = time.monotonic() - t0

    container = out_dir / "result.gcode.3mf"
    gcode = ""
    thumbnail = ""
    if code == 0 and container.is_file():
        try:
            gcode, thumbnail = _extract_gcode(container, out_dir)
        except (zipfile.BadZipFile, OSError) as exc:
            return SliceResult(ok=False, duration_sec=round(duration, 1),
                               error=f"切片产物解包失败:{exc!r}", log_tail=tail)
    if code != 0 or not gcode:
        key_lines = [ln for ln in tail if ln.strip() and (
            "error" in ln.lower() or "fail" in ln.lower() or "invalid" in ln.lower()
            or "can not" in ln.lower() or "No such" in ln)]
        detail = key_lines[-3:] if key_lines else tail[-3:]
        return SliceResult(ok=False, duration_sec=round(duration, 1),
                           error=f"切片失败(退出码 {code}):{' | '.join(detail) or '无输出'}",
                           log_tail=tail)
    est, grams = parse_gcode_stats(gcode)
    return SliceResult(ok=True, gcode_path=gcode, thumbnail_path=thumbnail,
                       duration_sec=round(duration, 1),
                       estimated_sec=est, filament_grams=grams, log_tail=tail)


_TIME_RE = re.compile(r";\s*estimated printing time[^=]*=\s*"
                      r"(?:(\d+)h)?\s*(?:(\d+)m)?\s*(?:(\d+)s)?", re.I)
_G_RE = re.compile(r";\s*filament used \[g\]\s*=\s*([\d.,\s]+)", re.I)


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
        # 多耗材逗号列表:取各通道之和(未用通道为 0)
        grams = sum(float(x) for x in m.group(1).split(",") if x.strip())
    return seconds, grams
