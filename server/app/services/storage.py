"""文件存储:统一放在 data_dir 下,数据库存相对路径,便于未来迁移到对象存储。"""
import re
from pathlib import Path

from app.core.config import settings

_UNSAFE = re.compile(r"[^\w.\-() \[\]]+", re.UNICODE)


def safe_name(name: str) -> str:
    """清理文件名中的路径分隔符与特殊字符(防目录穿越)。"""
    name = Path(name.replace("\\", "/")).name
    cleaned = _UNSAFE.sub("_", name).strip(". ")
    return cleaned[:180] or "unnamed"


def rel_model(user_id: int, model_id: int, filename: str) -> str:
    return f"models/u{user_id}/m{model_id}/{safe_name(filename)}"


def rel_gcode(user_id: int, job_id: int, filename: str) -> str:
    return f"gcode/u{user_id}/{safe_name(Path(filename).stem)}_{job_id}.gcode"


def rel_log(user_id: int, job_id: int) -> str:
    return f"logs/u{user_id}/job_{job_id}.log"


def abs_path(rel: str) -> Path:
    p = (settings.data_dir / rel).resolve()
    root = settings.data_dir.resolve()
    if not str(p).startswith(str(root)):
        raise ValueError("路径越界")
    p.parent.mkdir(parents=True, exist_ok=True)
    return p
