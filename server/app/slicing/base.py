"""切片层公共类型。实现方遵循同一 resolve+slice 契约。"""
from dataclasses import dataclass


@dataclass
class SliceEngineInfo:
    kind: str          # local / cloud(P1)
    name: str
    available: bool
    detail: str = ""
