"""切片参数包注册表:扫描 profiles/ 下的官方参数 JSON,供 API 层列出与选择。

目录约定:
  profiles/<机型key>/
    machine/   Creality K2 Plus.json、Creality K2 Plus 0.4 nozzle.json
    filament/  CR-PLA @Creality K2 Plus 0.4 nozzle.json ...
    process/   0.20mm Standard @Creality K2 Plus 0.4 nozzle.json ...

文件名里 " @" 前缀即为耗材/工艺展示名。
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

from app.core.config import settings


@dataclass
class ProfileChoice:
    id: str          # 文件名(相对 machine/filament/process 目录)
    name: str        # 展示名
    path: str        # 绝对路径


@dataclass
class MachineBundle:
    key: str                       # 目录名,如 creality_k2plus
    machines: list[ProfileChoice] = field(default_factory=list)
    filaments: list[ProfileChoice] = field(default_factory=list)
    processes: list[ProfileChoice] = field(default_factory=list)
    cover: str = ""                # 可选封面图路径


def _display_name(filename: str) -> str:
    return filename.rsplit(".json", 1)[0].split(" @", 1)[0] or filename


def _scan_dir(p: Path) -> list[ProfileChoice]:
    if not p.is_dir():
        return []
    out = []
    for f in sorted(p.glob("*.json")):
        out.append(ProfileChoice(id=f.name, name=_display_name(f.name),
                                 path=str(f)))
    return out


def list_bundles() -> list[MachineBundle]:
    root = settings.profiles_dir
    bundles: list[MachineBundle] = []
    if not root.is_dir():
        return bundles
    for d in sorted(root.iterdir()):
        if not d.is_dir():
            continue
        b = MachineBundle(key=d.name)
        b.machines = _scan_dir(d / "machine")
        b.filaments = _scan_dir(d / "filament")
        b.processes = _scan_dir(d / "process")
        cover = next((c for c in d.glob("*.png") or d.glob("*_cover.png")), None)
        if cover:
            b.cover = cover.name
        bundles.append(b)
    return bundles


def resolve_paths(bundle_key: str, machine_id: str, filament_ids: list[str],
                  process_id: str) -> tuple[list[str], list[str], str]:
    """把用户选择的 id 解析成绝对路径列表(供 CLI --load-* 参数)。"""
    root = settings.profiles_dir / bundle_key
    machine = [str(root / "machine" / machine_id)]
    filaments = [str(root / "filament" / f) for f in filament_ids]
    process = str(root / "process" / process_id)
    for p in [*machine, *filaments, process]:
        if not Path(p).is_file():
            raise FileNotFoundError(f"参数文件不存在:{p}")
    return machine, filaments, process


def read_profile_summary(path: str) -> dict:
    """读取参数 JSON 的关键字段(机型体积/耗材信息),用于 UI 展示。"""
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
    except Exception:
        return {}
    hits = {}
    for key in ("printer_model", "printable_area", "nozzle_diameter",
                "filament_type", "filament_diameter", "compatible_printers"):
        if key in data:
            hits[key] = data[key]
    return hits
