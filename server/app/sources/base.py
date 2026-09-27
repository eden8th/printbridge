"""模型源适配器接口。每个源(MakerWorld/Printables/...)实现同一套方法。

设计原则(合规):平台只是「用户授权拉取管道」——
文件按用户指令拉取、即切即传,不对外二次分发。
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import AsyncIterator, Callable


class SourceError(Exception):
    """模型源通用错误(网络/结构解析失败等)。"""


class SourceAuthError(SourceError):
    """未登录或凭证失效:需要用户在设置页更新账号 token。"""


@dataclass
class DesignSummary:
    id: str
    title: str
    cover: str = ""
    author: str = ""
    author_id: str = ""
    likes: int = 0
    downloads: int = 0


@dataclass
class DesignInstance:
    """设计下的一个可下载实例(= MakerWorld 的一次 profile 上传)。"""
    instance_id: str
    profile_id: str
    name: str = ""
    cover: str = ""
    downloads: int = 0


@dataclass
class DesignDetail:
    id: str
    title: str
    cover: str = ""
    author: str = ""
    summary_html: str = ""
    source_url: str = ""
    instances: list[DesignInstance] = field(default_factory=list)


ProgressCb = Callable[[int, int], None]  # (bytes_done, bytes_total)


class SourceAdapter(ABC):
    key: str = "base"
    name: str = "未命名源"

    @abstractmethod
    async def search(
        self, keyword: str, page: int = 1, page_size: int = 20, sort: str = "score"
    ) -> tuple[int, list[DesignSummary]]:
        """返回 (总数, 列表)。sort: score/downloadCount/likeCount/newUploads。"""

    @abstractmethod
    async def design(self, design_id: str) -> DesignDetail:
        """设计详情(含可下载实例列表)。"""

    @abstractmethod
    async def resolve_download(
        self, design: DesignDetail, instance: DesignInstance
    ) -> tuple[str, str]:
        """解析出 (签名直链, 文件名)。部分模型需要用户已配置凭证。"""

    @abstractmethod
    def download_stream(
        self, url: str, dest_path_abs: str, progress: ProgressCb | None = None
    ) -> AsyncIterator[bytes]:
        """把签名直链内容流式写入 dest_path_abs。"""

    async def aclose(self) -> None:  # pragma: no cover
        """释放底层连接池。"""
