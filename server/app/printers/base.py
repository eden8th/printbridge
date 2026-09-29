"""打印机适配器接口:把不同品牌/固件的差异压平成一个统一协议。

统一遥测字段(normalized):
  state: idle/printing/paused/finished/error/offline/unknown
  nozzle_temp/nozzle_target, bed_temp/bed_target, chamber_temp
  progress(0~1), filename, layer, remaining_sec

其他接入形态(如经中继转发)实现同一接口语义。
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import AsyncIterator


class PrinterError(Exception):
    pass


@dataclass
class Telemetry:
    state: str = "unknown"
    nozzle_temp: float | None = None
    nozzle_target: float | None = None
    bed_temp: float | None = None
    bed_target: float | None = None
    chamber_temp: float | None = None
    chamber_target: float | None = None
    progress: float | None = None
    filename: str = ""
    message: str = ""
    layer: str = ""
    cfs_connected: bool | None = None   # CFS 多色供料单元在线状态(创想 K 系列)
    remaining_sec: float | None = None
    raw: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        d = {k: v for k, v in self.__dict__.items() if k != "raw" and v is not None}
        return d


class PrinterAdapter(ABC):
    key: str = "base"
    name: str = "未命名适配器"

    def __init__(self, host: str, port: int | None = None, secret: str = "",
                 settings: dict | None = None) -> None:
        self.host = host
        self.port = port
        self.secret = secret or ""
        self.settings = settings or {}

    @abstractmethod
    async def status(self) -> Telemetry:
        """一次性拉取当前状态(注册打印机时的连通性测试也用它)。"""

    @abstractmethod
    async def send_file(self, local_path: str, remote_name: str) -> str:
        """上传 G-code,返回打印机侧文件名。"""

    @abstractmethod
    async def start_print(self, remote_name: str) -> None:
        """开始打印已上传的文件。"""

    @abstractmethod
    async def control(self, action: str) -> None:
        """pause / resume / stop。"""

    def stream(self) -> AsyncIterator[Telemetry]:
        """持续遥测流;不支持主动推送的实现可轮询。"""
        raise NotImplementedError

    async def cfs_status(self) -> dict | None:
        """CFS 料道状态;不适配的实现返回 None。

        返回 {"available": bool, "connected": bool, "boxes": [...], "raw": {...}},
        connected=True 表示当前有已识别(RFID)的装料料道。
        """
        return None

    async def select_slot(self, tnn: str) -> dict:
        """自动换料到指定料道(如 T1A);不适配的实现抛错。"""
        raise PrinterError("该打印机不支持料道切换")

    async def run_gcode(self, script: str) -> None:
        """发送原生 G-code;不支持原生指令的实现可忽略。"""
        return None

    async def ensure_ready(self, timeout: float = 90.0) -> str:
        """确保打印机可接受指令(如 Klipper shutdown 时自动恢复);
        不支持该概念的实现直接返回 ready。"""
        return "ready"
