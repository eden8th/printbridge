"""模型源注册表:API 层按 key 取适配器。"""
from __future__ import annotations

import re

from app.services.settings_service import get_setting
from app.sources.base import SourceAdapter, SourceError
from app.sources.makerworld import MakerWorldAdapter

_REGISTRY: dict[str, type[SourceAdapter]] = {
    MakerWorldAdapter.key: MakerWorldAdapter,
}

# 拓竹分享链接:makerworld.com/.cn 的 /models/{id}(兼容 zh/en 前缀与 #profileId-xxx)
_MW_URL_RE = re.compile(
    r"makerworld\.(?:com|com\.cn)/(?:[a-z-]+/)?models/(\d+)", re.I)
_MW_PROFILE_RE = re.compile(r"profileid-(\d+)", re.I)
# 创想云分享链接(识别用;自动导入待适配)
_CR_URL_RE = re.compile(r"crealitycloud\.(?:com|cn)/", re.I)


def parse_share_link(url: str) -> dict:
    """解析分享链接,返回 {source, design_id, profile_id?} 或 unsupported。"""
    url = (url or "").strip()
    m = _MW_URL_RE.search(url)
    if m:
        out = {"source": "makerworld", "design_id": m.group(1)}
        pm = _MW_PROFILE_RE.search(url)
        if pm:
            out["profile_id"] = pm.group(1)
        # 关键:国际站(.com)与国内站(com.cn)是两套独立 ID 空间,
        # 同一 ID 在两端对应完全不同的模型,必须按链接来源选择 API 区域
        out["region"] = "cn" if re.search(r"makerworld\.com\.cn", url, re.I) else "com"
        return out
    if _CR_URL_RE.search(url):
        return {"unsupported": True,
                "reason": "创想云链接导入即将支持(其模型接口需要进一步适配)"}
    return {"unsupported": True,
            "reason": "无法识别的链接,目前支持拓竹 MakerWorld 的模型分享链接"}


def source_keys() -> list[str]:
    return sorted(_REGISTRY)


def get_adapter_class(key: str) -> type[SourceAdapter]:
    try:
        return _REGISTRY[key]
    except KeyError as exc:
        raise SourceError(f"未知模型源:{key}") from exc


async def build_adapter(key: str, db,
                        region_override: str | None = None) -> SourceAdapter:
    """按 key 构造适配器,自动注入该源的全局凭证。

    region_override:链接解析出的来源区域,优先于用户设置。"""
    cls = get_adapter_class(key)
    kwargs: dict = {}
    if key == "makerworld":
        cfg = await get_setting(db, "makerworld")
        kwargs["token"] = str(cfg.get("token") or "")
        kwargs["region"] = region_override or str(cfg.get("region") or "cn")
    return cls(**kwargs)
