"""切片层公共类型。"""
from dataclasses import dataclass


@dataclass
class SliceEngineInfo:
    kind: str          # local
    name: str
    available: bool
    detail: str = ""
