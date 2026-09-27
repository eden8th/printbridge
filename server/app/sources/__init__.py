"""模型源注册表:API 层按 key 取适配器。"""
from __future__ import annotations

from app.services.settings_service import get_setting
from app.sources.base import SourceAdapter, SourceError
from app.sources.makerworld import MakerWorldAdapter

_REGISTRY: dict[str, type[SourceAdapter]] = {
    MakerWorldAdapter.key: MakerWorldAdapter,
}


def source_keys() -> list[str]:
    return sorted(_REGISTRY)


def get_adapter_class(key: str) -> type[SourceAdapter]:
    try:
        return _REGISTRY[key]
    except KeyError as exc:
        raise SourceError(f"未知模型源:{key}") from exc


async def build_adapter(key: str, db) -> SourceAdapter:
    """按 key 构造适配器,自动注入该源的用户凭证。"""
    cls = get_adapter_class(key)
    kwargs: dict = {}
    if key == "makerworld":
        cfg = await get_setting(db, "makerworld")
        kwargs["token"] = str(cfg.get("token") or "")
        kwargs["region"] = str(cfg.get("region") or "cn")
    return cls(**kwargs)
