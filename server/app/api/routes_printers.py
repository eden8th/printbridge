"""打印机管理:注册/探测/控制/手动打印。"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, field_validator
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import current_user, get_db
from app.models import ModelFile, Printer, User
from app.printers import adapter_keys, build_adapter, manager
from app.printers.discovery import discover
from app.services import storage

router = APIRouter(prefix="/api/printers", tags=["printers"])


class PrinterBody(BaseModel):
    name: str
    adapter: str                 # creality_ws / moonraker
    host: str
    port: int | None = None
    secret: str = ""
    settings: dict = {}

    @field_validator("port", mode="before")
    @classmethod
    def _empty_port_to_none(cls, v):
        """前端 number 输入框留空会提交 "",归一为 None(用适配器默认端口)。"""
        if v in ("", None):
            return None
        return v

    @field_validator("name", "host")
    @classmethod
    def _not_blank(cls, v: str) -> str:
        v = (v or "").strip()
        if not v:
            raise ValueError("不能为空")
        return v


@router.get("")
async def list_printers(db: AsyncSession = Depends(get_db),
                        user: User = Depends(current_user)):
    res = await db.execute(select(Printer).where(Printer.user_id == user.id)
                           .order_by(Printer.id))
    return [{"id": p.id, "name": p.name, "adapter": p.adapter, "host": p.host,
             "port": p.port, "is_enabled": p.is_enabled,
             "settings": p.settings,
             "telemetry": manager.latest(p.id)} for p in res.scalars()]


@router.get("/adapters")
async def list_adapters():
    return adapter_keys()


class DiscoverBody(BaseModel):
    cidr: str | None = None   # 可选,如 192.168.8.0/24;默认自动探测本机网段


@router.post("/discover")
async def discover_printers(body: DiscoverBody):
    """扫描局域网,自动发现创想 K 系列 / Klipper(Moonraker)打印机。只读探测。"""
    try:
        return await discover(body.cidr)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc


@router.post("")
async def add_printer(body: PrinterBody, db: AsyncSession = Depends(get_db),
                      user: User = Depends(current_user)):
    p = Printer(user_id=user.id, name=body.name, adapter=body.adapter,
                host=body.host, port=body.port, secret=body.secret,
                settings=body.settings)
    db.add(p)
    await db.commit()
    await db.refresh(p)
    manager.ensure_loop(p)
    return {"id": p.id}


@router.put("/{printer_id}")
async def update_printer(printer_id: int, body: PrinterBody,
                         db: AsyncSession = Depends(get_db),
                         user: User = Depends(current_user)):
    p = await db.get(Printer, printer_id)
    if p is None or p.user_id != user.id:
        raise HTTPException(404, "打印机不存在")
    p.name, p.adapter, p.host = body.name, body.adapter, body.host
    p.port, p.secret, p.settings = body.port, body.secret, body.settings
    await db.commit()
    manager.stop(printer_id)   # 让遥测循环用新配置重建
    manager.ensure_loop(p)
    return {"ok": True}


@router.delete("/{printer_id}")
async def delete_printer(printer_id: int, db: AsyncSession = Depends(get_db),
                         user: User = Depends(current_user)):
    p = await db.get(Printer, printer_id)
    if p is None or p.user_id != user.id:
        raise HTTPException(404, "打印机不存在")
    manager.stop(printer_id)
    await db.delete(p)
    await db.commit()
    return {"ok": True}


@router.get("/{printer_id}/cfs")
async def printer_cfs(printer_id: int, db: AsyncSession = Depends(get_db),
                      user: User = Depends(current_user)):
    """CFS 料道状态(connected=True 时 raw 内含已识别的颜色/材质)。"""
    p = await db.get(Printer, printer_id)
    if p is None or p.user_id != user.id:
        raise HTTPException(404, "打印机不存在")
    adapter = build_adapter(p)
    try:
        result = await adapter.cfs_status()
        return result or {"available": False, "connected": False, "raw": {}}
    except Exception as exc:  # noqa: BLE001
        return {"available": False, "connected": False, "error": str(exc)}
    finally:
        if hasattr(adapter, "aclose"):
            await adapter.aclose()


@router.post("/{printer_id}/test")
async def test_printer(printer_id: int, db: AsyncSession = Depends(get_db),
                       user: User = Depends(current_user)):
    """连通性测试:返回一次归一化遥测。"""
    p = await db.get(Printer, printer_id)
    if p is None or p.user_id != user.id:
        raise HTTPException(404, "打印机不存在")
    adapter = build_adapter(p)
    try:
        tel = await adapter.status()
        return tel.to_dict()
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(502, str(exc)) from exc
    finally:
        if hasattr(adapter, "aclose"):
            await adapter.aclose()


class ControlBody(BaseModel):
    action: str  # pause / resume / stop


@router.post("/{printer_id}/control")
async def control_printer(printer_id: int, body: ControlBody,
                          db: AsyncSession = Depends(get_db),
                          user: User = Depends(current_user)):
    p = await db.get(Printer, printer_id)
    if p is None or p.user_id != user.id:
        raise HTTPException(404, "打印机不存在")
    adapter = build_adapter(p)
    try:
        await adapter.control(body.action)
        return {"ok": True}
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(502, str(exc)) from exc
    finally:
        if hasattr(adapter, "aclose"):
            await adapter.aclose()


class ManualPrintBody(BaseModel):
    file_id: int          # 库内文件(3mf/stl 不行,仅已切好的 gcode)
    auto_start: bool = True


@router.post("/{printer_id}/print-file")
async def print_existing(printer_id: int, body: ManualPrintBody,
                         db: AsyncSession = Depends(get_db),
                         user: User = Depends(current_user)):
    """手动把库内 G-code 发到打印机(绕过切片)。"""
    f = await db.get(ModelFile, body.file_id)
    if f is None or f.user_id != user.id:
        raise HTTPException(404, "文件不存在")
    if f.kind != "gcode":
        raise HTTPException(400, "只能直接打印 G-code 文件")
    p = await db.get(Printer, printer_id)
    if p is None or p.user_id != user.id:
        raise HTTPException(404, "打印机不存在")
    adapter = build_adapter(p)
    try:
        remote = await adapter.send_file(str(storage.abs_path(f.path)), f.name)
        if body.auto_start:
            await adapter.start_print(remote)
        return {"ok": True, "remote_file": remote}
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(502, str(exc)) from exc
    finally:
        if hasattr(adapter, "aclose"):
            await adapter.aclose()
