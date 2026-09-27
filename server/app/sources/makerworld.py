"""MakerWorld(拓竹模型市场)适配器。

接口全部走 Bambu Cloud 官方 App 同源后端(api.bambulab.cn / .com),
不经过 makerworld.com 网页(Cloudflare 反爬),这是社区逆向并长期
验证过的稳定路径(参见 Thingport / bambuddy / bambu-studio-ai 等项目)。

- 搜索/设计详情:免认证
- 解析 3MF 下载直链:需要 Bearer token —— 用户在设置页粘贴自己浏览器
  Cookie 中的 `token` 值(「用户授权拉取管道」模式,平台不托管账号)
- 限速:全局 1 req/s,礼貌访问
"""
from __future__ import annotations

import asyncio
import time
from pathlib import Path
from typing import Any, AsyncIterator

import httpx

from app.sources.base import (
    DesignDetail,
    DesignInstance,
    DesignSummary,
    ProgressCb,
    SourceAdapter,
    SourceAuthError,
    SourceError,
)

_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/126.0 Safari/537.36"
)
_ORDER_BY = {"score": "score", "downloadCount": "downloadCount",
             "likeCount": "likeCount", "newUploads": "newUploads", "hotScore": "hotScore"}


class MakerWorldAdapter(SourceAdapter):
    key = "makerworld"
    name = "MakerWorld(拓竹)"

    def __init__(self, token: str = "", region: str = "cn") -> None:
        # region: cn=国内(默认,中文数据) / com=国际
        host = "api.bambulab.cn" if region == "cn" else "api.bambulab.com"
        self._base = f"https://{host}"
        self._token = (token or "").strip()
        self._client = httpx.AsyncClient(
            timeout=httpx.Timeout(20.0, read=60.0),
            headers={"User-Agent": _UA, "Accept": "application/json",
                     "Referer": "https://makerworld.com/"},
            follow_redirects=True,
        )
        self._last_req = 0.0

    async def aclose(self) -> None:
        await self._client.aclose()

    async def _rate_limit(self) -> None:
        gap = 1.0 - (time.monotonic() - self._last_req)
        if gap > 0:
            await asyncio.sleep(gap)
        self._last_req = time.monotonic()

    def _auth_headers(self) -> dict[str, str]:
        if not self._token:
            raise SourceAuthError("尚未配置 MakerWorld 凭证:请在设置页粘贴账号 token")
        return {"Authorization": f"Bearer {self._token}"}

    async def _get_json(self, path: str, params: dict[str, Any] | None = None,
                        auth: bool = False) -> dict[str, Any]:
        await self._rate_limit()
        headers = self._auth_headers() if auth else {}
        try:
            resp = await self._client.get(f"{self._base}{path}", params=params,
                                          headers=headers)
        except httpx.HTTPError as exc:
            raise SourceError(f"MakerWorld 网络错误:{exc}") from exc
        if resp.status_code in (401, 403):
            raise SourceAuthError("MakerWorld 凭证无效或已过期,请更新设置页 token")
        if resp.status_code == 418:
            raise SourceError("触发 MakerWorld 限流(418),请稍后再试")
        resp.raise_for_status()
        try:
            return resp.json()
        except ValueError as exc:
            raise SourceError("MakerWorld 返回了非 JSON 内容") from exc

    # ---- 搜索 ----------------------------------------------------------
    async def search(self, keyword: str, page: int = 1, page_size: int = 20,
                     sort: str = "score") -> tuple[int, list[DesignSummary]]:
        body = await self._get_json("/v1/search-service/select/design2", params={
            "keyword": keyword,
            "limit": max(1, min(page_size, 50)),
            "offset": (max(1, page) - 1) * page_size,
            "orderBy": _ORDER_BY.get(sort, "score"),
        })
        if body.get("keywordBlock"):
            return 0, []
        hits = body.get("hits") or []
        items: list[DesignSummary] = []
        for hit in hits:
            if not isinstance(hit, dict) or hit.get("nsfw") is True:
                continue
            creator = hit.get("designCreator") or {}
            items.append(DesignSummary(
                id=str(hit.get("id", "")),
                title=str(hit.get("title") or hit.get("slug") or "未命名"),
                cover=str(hit.get("cover") or ""),
                author=str(creator.get("name") or ""),
                author_id=str(creator.get("uid") or ""),
                likes=int(hit.get("likeCount") or 0),
                downloads=int(hit.get("downloadCount") or 0),
            ))
        return int(body.get("total") or len(items)), items

    # ---- 设计详情 ------------------------------------------------------
    async def design(self, design_id: str) -> DesignDetail:
        d = await self._get_json(f"/v1/design-service/design/{int(design_id)}")
        if not isinstance(d, dict) or not d.get("id"):
            raise SourceError("未找到该设计")
        instances = [
            DesignInstance(
                instance_id=str(i.get("id", "")),
                profile_id=str(i.get("profileId", "")),
                name=str(i.get("name") or i.get("title") or f"实例 {i.get('id')}"),
                cover=str(i.get("cover") or ""),
                downloads=int(i.get("downloadCount") or 0),
            )
            for i in (d.get("instances") or []) if isinstance(i, dict)
        ]
        creator = d.get("designCreator") or {}
        detail = DesignDetail(
            id=str(d["id"]),
            title=str(d.get("title") or d.get("slug") or "未命名"),
            cover=str(d.get("coverUrl") or ""),
            author=str(creator.get("nickName") or creator.get("name") or ""),
            summary_html=str(d.get("summary") or ""),
            source_url=f"https://makerworld.com/zh/models/{d['id']}",
            instances=instances,
        )
        # instances 为空时兜底拉独立实例接口
        if not detail.instances:
            try:
                env = await self._get_json(
                    f"/v1/design-service/design/{int(design_id)}/instances")
                for i in env.get("instances") or []:
                    if isinstance(i, dict):
                        detail.instances.append(DesignInstance(
                            instance_id=str(i.get("id", "")),
                            profile_id=str(i.get("profileId", "")),
                            name=str(i.get("name") or f"实例 {i.get('id')}"),
                            cover=str(i.get("cover") or ""),
                            downloads=int(i.get("downloadCount") or 0),
                        ))
            except SourceError:
                pass
        return detail

    # ---- 下载 ----------------------------------------------------------
    async def resolve_download(
        self, design: DesignDetail, instance: DesignInstance
    ) -> tuple[str, str]:
        d = await self._get_json(
            f"/v1/design-service/design/{int(design.id)}")
        model_id = d.get("modelId")
        if not model_id:
            raise SourceError("设计缺少 modelId,无法解析下载")
        body = await self._get_json(
            f"/v1/iot-service/api/user/profile/{instance.profile_id}",
            params={"model_id": str(model_id)}, auth=True,
        )
        if body.get("code") == 4 or body.get("error"):
            raise SourceAuthError("下载需要登录:请在设置页配置 MakerWorld token")
        url = str(body.get("url") or "")
        if not url:
            raise SourceError("MakerWorld 未返回下载直链")
        filename = str(body.get("filename") or f"{design.title}.3mf")
        return url, filename

    async def download_stream(
        self, url: str, dest_path_abs: str, progress: ProgressCb | None = None
    ) -> AsyncIterator[bytes]:
        # 签名 S3 直链,无需鉴权头;流式写盘,回调进度
        async with httpx.AsyncClient(timeout=httpx.Timeout(20.0, read=120.0),
                                     follow_redirects=True) as client:
            async with client.stream("GET", url,
                                     headers={"User-Agent": _UA}) as resp:
                resp.raise_for_status()
                total = int(resp.headers.get("content-length") or 0)
                done = 0
                Path(dest_path_abs).parent.mkdir(parents=True, exist_ok=True)
                with open(dest_path_abs, "wb") as fh:
                    async for chunk in resp.aiter_bytes(64 * 1024):
                        fh.write(chunk)
                        done += len(chunk)
                        if progress:
                            progress(done, total)
                    yield b""  # 确认写入完成
