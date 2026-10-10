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
    argv = [exe, "--allow-newer-file"]
    # allow-newer-file:MakerWorld 现下发新版 Bambu Studio 产出的工程 3MF
    # (版本号如 2.5.x > Orca 自身 2.4.x),默认按 CLI_FILE_VERSION_NOT_SUPPORTED(-24)
    # 拒载;内嵌配置本就会被我们的 --load-settings 覆盖,跳过版本门槛是安全的。
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
    from app.core.config import settings
    timed_out = False
    try:
        assert proc.stdout is not None
        for raw in proc.stdout:
            line = raw.decode("utf-8", "replace").rstrip()
            tail.append(line)
            if len(tail) > 400:
                tail = tail[-400:]
            if logf:
                logf.write(raw)
        code = proc.wait(timeout=settings.slice_timeout)
    except subprocess.TimeoutExpired:
        # 防呆:切片子进程挂死时按时限回收,而非无限占用
        timed_out = True
        proc.kill()
        code = proc.wait()
        tail.append(f"[timeout] 切片超过 {settings.slice_timeout}s,已强制终止")
    finally:
        if logf:
            logf.close()
        if proc.poll() is None:
            proc.kill()
    if timed_out:
        return -9, tail
    return code, tail


def _inject_thumbnails(gcode_path: str, png_path: str,
                       sizes: tuple[tuple[int, int], ...] = ((96, 96), (300, 300))) -> None:
    """把板预览 PNG 以 Creality 规格的 base64 注释块注入 G-code 头部。

    K2 系列屏幕从 G-code 注释读取缩略图(`; thumbnail begin WxH <len>`),
    而 Orca 2.4.2 CLI 切片不输出该块(GUI 才有),故自行注入;
    规格与 Creality Print 产物一致(96x96 + 300x300 PNG,每行 78 字符 base64)。
    """
    import base64
    import io

    try:
        from PIL import Image
        img = Image.open(png_path).convert("RGB")
    except Exception:  # noqa: BLE001  无 pillow/图片损坏时跳过,不影响切片产物
        return
    blocks = []
    for w, h in sizes:
        buf = io.BytesIO()
        img.resize((w, h)).save(buf, "PNG", optimize=True)
        b64 = base64.b64encode(buf.getvalue()).decode()
        lines = [f"; thumbnail begin {w}x{h} {len(b64)}"]
        lines += ["; " + b64[i:i + 78] for i in range(0, len(b64), 78)]
        lines.append("; thumbnail end")
        blocks.append("\n".join(lines))
    payload = "; THUMBNAIL_BLOCK_START\n" + "\n;\n".join(blocks) + "\n; THUMBNAIL_BLOCK_END\n"

    with open(gcode_path, "r", encoding="utf-8", errors="replace") as fh:
        text = fh.read()
    marker = "; HEADER_BLOCK_END"
    idx = text.find(marker)
    if idx < 0:
        return
    pos = text.find("\n", idx) + 1
    with open(gcode_path, "w", encoding="utf-8", newline="") as fh:
        fh.write(text[:pos] + payload + text[pos:])


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
        _inject_thumbnails(str(target), thumb)
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
    """从 Orca 系 G-code 提取预估时长与耗材克重。解析不出返回 (0,0)。

    Orca v2.4.x 把统计块写在文件尾部(estimated printing time / filament used),
    旧版在头部,故头尾都扫。"""
    try:
        import os
        with open(gcode_path, "r", encoding="utf-8", errors="replace") as fh:
            head = "".join(fh.readline() for _ in range(400))
            fh.seek(0, os.SEEK_END)
            size = fh.tell()
            fh.seek(max(0, size - 65536))
            tail = fh.read()
    except OSError:
        return 0.0, 0.0
    text = head + "\n" + tail
    seconds = 0.0
    m = _TIME_RE.search(text)
    if m:
        h, mi, s = (int(x or 0) for x in m.groups())
        seconds = h * 3600 + mi * 60 + s
    grams = 0.0
    m = _G_RE.search(text)
    if m:
        # 多耗材逗号列表:取各通道之和(未用通道为 0)
        grams = sum(float(x) for x in m.group(1).split(",") if x.strip())
    return seconds, grams
