"""切片参数包注册表:按「机型 - 喷嘴 - 耗材/工艺」解析官方参数 JSON。

目录约定(profiles/<机型key>/):
  machine/   Creality K2 Plus.json(基础) + Creality K2 Plus 0.4 nozzle.json(可打印变体)
  filament/  CR-PLA @Creality K2 Plus 0.4 nozzle.json ...
  process/   0.20mm Standard @Creality K2 Plus 0.4 nozzle.json ...

文件名规律:`<名> @<机型> <喷嘴> nozzle.json`,据此分组;耗材材质类型从
JSON 内的 filament_type 读取(带缓存)。
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path

from app.core.config import settings

NOZZLE_RE = re.compile(r"^(?P<base>.+?)\s+(?P<nozzle>\d+(?:\.\d+)?)\s+nozzle\.json$")


@dataclass
class NozzleOption:
    nozzle: str            # "0.4"
    machine_id: str        # machine 目录里的文件名


@dataclass
class FilamentItem:
    id: str                # 文件名
    name: str              # 展示名(CR-PLA)
    ftype: str             # JSON 内 filament_type(PLA)


@dataclass
class ProcessItem:
    id: str
    name: str              # 0.20mm Standard


@dataclass
class MachineBundle:
    key: str
    name: str              # 机型基础名(Creality K2 Plus)
    nozzles: list[NozzleOption] = field(default_factory=list)
    filaments: dict[str, list[FilamentItem]] = field(default_factory=dict)
    processes: dict[str, list[ProcessItem]] = field(default_factory=dict)


_meta_cache: dict[str, str] = {}


def _filament_type(path: Path) -> str:
    """读取耗材 JSON 的 filament_type(带缓存,避免每次请求都读 160 个文件)。"""
    key = f"{path}:{path.stat().st_mtime_ns}"
    if key not in _meta_cache:
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            ft = data.get("filament_type")
            _meta_cache[key] = (ft[0] if isinstance(ft, list) and ft else str(ft or ""))
        except Exception:
            _meta_cache[key] = ""
        if len(_meta_cache) > 2000:   # 防缓存无限膨胀
            _meta_cache.clear()
    return _meta_cache[key]


def _split_name(filename: str) -> tuple[str, str] | None:
    """'CR-PLA @Creality K2 Plus 0.4 nozzle.json' -> ('CR-PLA', '0.4')"""
    m = NOZZLE_RE.match(filename)
    if not m:
        return None
    return m.group("base").split(" @", 1)[0], m.group("nozzle")


def list_bundles() -> list[MachineBundle]:
    root = settings.profiles_dir
    bundles: list[MachineBundle] = []
    if not root.is_dir():
        return bundles
    for d in sorted(root.iterdir()):
        if not d.is_dir():
            continue
        machine_dir = d / "machine"
        if not machine_dir.is_dir():
            continue
        nozzles: list[NozzleOption] = []
        base_name = ""
        for f in sorted(machine_dir.glob("*.json")):
            m = NOZZLE_RE.match(f.name)
            if m:
                nozzles.append(NozzleOption(nozzle=m.group("nozzle"), machine_id=f.name))
                base_name = base_name or m.group("base")
        if not nozzles:
            continue
        b = MachineBundle(key=d.name, name=base_name, nozzles=nozzles)
        for sub, items_cls in (("filament", FilamentItem), ("process", ProcessItem)):
            parsed: dict[str, list] = {}
            for f in sorted((d / sub).glob("*.json")):
                sp = _split_name(f.name)
                if not sp:
                    continue
                name, nozzle = sp
                if items_cls is FilamentItem:
                    parsed.setdefault(nozzle, []).append(
                        FilamentItem(id=f.name, name=name, ftype=_filament_type(f)))
                else:
                    parsed.setdefault(nozzle, []).append(
                        ProcessItem(id=f.name, name=name))
            if items_cls is FilamentItem:
                b.filaments = parsed
            else:
                b.processes = parsed
        bundles.append(b)
    return bundles


def get_bundle(key: str) -> MachineBundle:
    for b in list_bundles():
        if b.key == key:
            return b
    raise FileNotFoundError(f"参数包不存在:{key}")


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


def prepare_filament_files(filament_paths: list[str], colors: list[str],
                           workdir: Path) -> list[str]:
    """按用户选色生成耗材配置副本(覆盖 filament_colour),返回新路径列表。

    官方耗材 JSON 不带颜色;CFS 打印时颜色参与料道匹配,因此用户选择的
    颜色必须写进切片配置。未指定颜色的文件原样使用。
    """
    out: list[str] = []
    workdir.mkdir(parents=True, exist_ok=True)
    for i, p in enumerate(filament_paths):
        color = (colors[i] if i < len(colors) else "") or ""
        hexv = color.lstrip("#").strip()
        if not re.fullmatch(r"[0-9a-fA-F]{6}([0-9a-fA-F]{2})?", hexv):
            out.append(p)
            continue
        hexv = (hexv + "FF")[:8] if len(hexv) == 6 else hexv.upper()
        try:
            data = json.loads(Path(p).read_text(encoding="utf-8"))
        except Exception:
            out.append(p)
            continue
        data["filament_colour"] = [f"#{hexv}"]
        target = workdir / f"fil_{i}_{Path(p).name}"
        target.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
        out.append(str(target))
    return out


def read_profile_summary(path: str) -> dict:
    """读取参数 JSON 的关键字段,用于 UI 展示。"""
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
