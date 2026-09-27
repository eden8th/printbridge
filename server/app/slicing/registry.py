"""切片参数包注册表:按「机型 - 喷嘴 - 耗材/工艺」解析 Orca 系官方参数 JSON。

目录约定:profiles/<目录名>/{machine,filament,process}/,目录内可混放多个
机型(如 Orca 官方 Creality 目录 143 个机器文件),registry 按文件名规律
`<机型> <喷嘴> nozzle.json` 自动分组为多个机型 bundle:
  machine:  "Creality K2 Pro 0.4 nozzle.json" → base="Creality K2 Pro" nozzle=0.4
  filament: "CR-PLA @Creality K2 Pro 0.4 nozzle.json"
bundle key = 机型名去符号小写(如 crealityk2pro),与打印机 settings.model 对应。
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path

from app.core.config import settings

NOZZLE_RE = re.compile(r"^(?P<base>.+?)\s+(?P<nozzle>\d+(?:\.\d+)?)\s+nozzle\.json$")
# Orca 官方耗材命名:"CR-PLA @K2 Pro-all.json"(机型简称,-all=全喷嘴通用)
ALL_RE = re.compile(r"^(?P<name>.+?)\s+@(?P<machine>.+?)-all\.json$")


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
    key: str               # 机型 slug,如 crealityk2pro
    name: str              # 机型基础名(Creality K2 Pro)
    dir: Path              # 所在参数目录
    nozzles: list[NozzleOption] = field(default_factory=list)
    filaments: dict[str, list[FilamentItem]] = field(default_factory=dict)
    processes: dict[str, list[ProcessItem]] = field(default_factory=dict)


_meta_cache: dict[str, str] = {}

# Orca 部分官方耗材 JSON 缺 filament_type,按名称推断兜底
_TYPE_WORDS = ["PETG", "PLA-CF", "PLA", "ABS", "TPU", "NYLON", "ASA",
               "PA-CF", "PAHT-CF", "PET-CF", "PVA", "HIPS", "PA"]


def _infer_type_from_name(name: str) -> str:
    up = name.upper()
    for w in _TYPE_WORDS:
        if w in up:
            return w
    return ""


def _filament_type(path: Path, name: str = "") -> str:
    """读取耗材 JSON 的 filament_type(带缓存);缺失时按名称推断。"""
    try:
        key = f"{path}:{path.stat().st_mtime_ns}"
    except OSError:
        return ""
    if key not in _meta_cache:
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            ft = data.get("filament_type")
            _meta_cache[key] = (ft[0] if isinstance(ft, list) and ft else str(ft or ""))
        except Exception:
            _meta_cache[key] = ""
        if not _meta_cache[key]:
            _meta_cache[key] = _infer_type_from_name(name)
        if len(_meta_cache) > 4000:
            _meta_cache.clear()
    return _meta_cache[key]


def _split_name(filename: str) -> tuple[str, str, str | None] | None:
    """解析耗材/工艺文件名 → (展示名, 机型, 喷嘴)。

    兼容两种命名:
      'CR-PLA @Creality K2 Pro 0.4 nozzle.json' → ('CR-PLA', 'Creality K2 Pro', '0.4')
      'CR-PLA @K2 Pro-all.json'                 → ('CR-PLA', 'K2 Pro', None=全喷嘴)
    """
    m = NOZZLE_RE.match(filename)
    if m:
        name, sep, base = m.group("base").rpartition(" @")
        return (name or base), (base or m.group("base")), m.group("nozzle")
    m = ALL_RE.match(filename)
    if m:
        return m.group("name"), m.group("machine"), None
    return None


def _slug(base: str) -> str:
    return re.sub(r"[^a-z0-9]", "", base.lower())


def _norm_short(base: str) -> str:
    """机型名规范化(去掉 Creality 前缀),用于匹配 Orca 耗材的机型简称。"""
    return _slug(re.sub(r"^creality\s+", "", base.strip(), flags=re.I))


def list_bundles() -> list[MachineBundle]:
    root = settings.profiles_dir
    bundles: list[MachineBundle] = []
    if not root.is_dir():
        return bundles
    for d in sorted(root.iterdir()):
        machine_dir = d / "machine"
        if not d.is_dir() or not machine_dir.is_dir():
            continue
        groups: dict[str, list[NozzleOption]] = {}
        for f in sorted(machine_dir.glob("*.json")):
            m = NOZZLE_RE.match(f.name)
            if m:
                groups.setdefault(m.group("base"), []).append(
                    NozzleOption(nozzle=m.group("nozzle"), machine_id=f.name))
        for base, nozzles in sorted(groups.items()):
            key = _slug(base)
            if not key:
                continue
            b = MachineBundle(key=key, name=base, dir=d, nozzles=nozzles)
            # 工艺:带喷嘴的完整命名,按 base 精确归属
            for f in sorted((d / "process").glob("*.json")):
                sp = _split_name(f.name)
                if not sp or sp[1] != base or sp[2] is None:
                    continue
                b.processes.setdefault(sp[2], []).append(
                    ProcessItem(id=f.name, name=sp[0]))
            bundles.append(b)

    # 耗材:Orca 命名用机型简称且全喷嘴通用,按规范化名归属到所有喷嘴
    by_short: dict[tuple[Path, str], MachineBundle] = {}
    for b in bundles:
        by_short.setdefault((b.dir, _norm_short(b.name)), b)
    for d in sorted(root.iterdir()):
        fil_dir = d / "filament"
        if not d.is_dir() or not fil_dir.is_dir():
            continue
        for f in sorted(fil_dir.glob("*.json")):
            sp = _split_name(f.name)
            if not sp:
                continue
            name, machine, nozzle = sp
            b = by_short.get((d, _norm_short(machine)))
            if b is None:
                continue
            item = FilamentItem(id=f.name, name=name,
                                ftype=_filament_type(f, name))
            targets = [n.nozzle for n in b.nozzles] if nozzle is None else [nozzle]
            for nz in targets:
                b.filaments.setdefault(nz, []).append(item)

    for b in bundles:
        for items in list(b.filaments.values()) + list(b.processes.values()):
            items.sort(key=lambda x: (x.name, x.id))
    return bundles


def get_bundle(key: str) -> MachineBundle:
    for b in list_bundles():
        if b.key == key:
            return b
    raise FileNotFoundError(f"参数包不存在:{key}")


def resolve_paths(bundle_key: str, machine_id: str, filament_ids: list[str],
                  process_id: str) -> tuple[list[str], list[str], str]:
    """把用户选择的 id 解析成绝对路径列表(供 CLI --load-* 参数)。"""
    b = get_bundle(bundle_key)
    machine = [str(b.dir / "machine" / machine_id)]
    filaments = [str(b.dir / "filament" / f) for f in filament_ids]
    process = str(b.dir / "process" / process_id)
    for p in [*machine, *filaments, process]:
        if not Path(p).is_file():
            raise FileNotFoundError(f"参数文件不存在:{p}")
    return machine, filaments, process


def prepare_filament_files(filament_paths: list[str], colors: list[str],
                           workdir: Path) -> list[str]:
    """按用户选色生成耗材配置副本(覆盖 filament_colour),返回新路径列表。

    颜色参与 CFS 料道匹配;未指定颜色的文件原样使用。
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
