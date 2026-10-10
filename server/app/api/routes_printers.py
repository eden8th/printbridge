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


@router.get("/{printer_id}/camera")
async def printer_camera(printer_id: int, db: AsyncSession = Depends(get_db),
                         user: User = Depends(current_user)):
    """打印机摄像头快照(JPEG)。

    Moonraker 机型:优先取 /server/webcams/list 注册的快照地址,
    退回常见 mjpeg-streamer 路径;创想 K 系列(creality_ws)摄像头走
    私有 WebRTC 协议(9999 信令),无本地 HTTP 快照,明确返回不可用。
    """
    from fastapi.responses import Response

    p = await db.get(Printer, printer_id)
    if p is None or p.user_id != user.id:
        raise HTTPException(404, "打印机不存在")
    adapter = build_adapter(p)
    try:
        frame = await adapter.camera_frame()
        if frame:
            return Response(frame, media_type="image/jpeg")
    except Exception:  # noqa: BLE001  适配器取帧失败落到 go2rtc 兜底
        pass
    finally:
        if hasattr(adapter, "aclose"):
            await adapter.aclose()
    # go2rtc sidecar 兜底(创想 K 系私有 WebRTC;须 host 网络容器)
    from app.services.camera import go2rtc_frame
    data = await go2rtc_frame(p.id, p.host)
    if data:
        return Response(data, media_type="image/jpeg")
    raise HTTPException(404, "未找到可用的摄像头快照(该机型可能使用私有视频协议)")


@router.get("/{printer_id}/light")
async def get_light(printer_id: int, db: AsyncSession = Depends(get_db),
                    user: User = Depends(current_user)):
    """腔体灯状态(on=true 开);不可查返回 on=null。"""
    p = await db.get(Printer, printer_id)
    if p is None or p.user_id != user.id:
        raise HTTPException(404, "打印机不存在")
    adapter = build_adapter(p)
    try:
        return {"on": await adapter.light_state()}
    finally:
        if hasattr(adapter, "aclose"):
            await adapter.aclose()


class LightBody(BaseModel):
    on: bool


@router.post("/{printer_id}/light")
async def set_light(printer_id: int, body: LightBody,
                    db: AsyncSession = Depends(get_db),
                    user: User = Depends(current_user)):
    """开关腔体灯。"""
    p = await db.get(Printer, printer_id)
    if p is None or p.user_id != user.id:
        raise HTTPException(404, "打印机不存在")
    adapter = build_adapter(p)
    try:
        await adapter.set_light(body.on)
        return {"ok": True, "on": body.on}
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(400, str(exc)) from exc
    finally:
        if hasattr(adapter, "aclose"):
            await adapter.aclose()


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
    """CFS 料道状态(connected=True 时 raw 内含已识别的颜色/材质)。

    每个 slot 合并手工记录的库存克数(settings.inventory,RFID 不上报余量)。"""
    p = await db.get(Printer, printer_id)
    if p is None or p.user_id != user.id:
        raise HTTPException(404, "打印机不存在")
    adapter = build_adapter(p)
    try:
        result = await adapter.cfs_status()
        result = result or {"available": False, "connected": False, "raw": {}}
        inv = (p.settings or {}).get("inventory") or {}
        for box in result.get("boxes") or []:
            for slot in box.get("slots") or []:
                tnn = str(slot.get("slot") or "").upper()
                if tnn in inv:
                    slot["grams"] = inv[tnn]
        return result
    except Exception as exc:  # noqa: BLE001
        return {"available": False, "connected": False, "error": str(exc)}
    finally:
        if hasattr(adapter, "aclose"):
            await adapter.aclose()


class InventoryBody(BaseModel):
    items: list[dict]   # [{tnn: "T1A", grams: 850}];grams 传 null 清除记录

    @field_validator("items")
    @classmethod
    def _validate_items(cls, v):
        import re
        for item in v:
            if not isinstance(item, dict) or not re.fullmatch(r"T\d[A-D]",
                                                             str(item.get("tnn", ""))):
                raise ValueError("料道标识应为 T1A~T4D")
            grams = item.get("grams")
            if grams is not None and (not isinstance(grams, (int, float)) or grams < 0):
                raise ValueError("克数应为非负数字")
        return v


@router.put("/{printer_id}/inventory")
async def set_inventory(printer_id: int, body: InventoryBody,
                        db: AsyncSession = Depends(get_db),
                        user: User = Depends(current_user)):
    """手工记录各料道库存克数(CFS RFID 不上报余量,打印前据此校验够不够打)。"""
    p = await db.get(Printer, printer_id)
    if p is None or p.user_id != user.id:
        raise HTTPException(404, "打印机不存在")
    settings = dict(p.settings or {})
    inv = dict(settings.get("inventory") or {})
    for item in body.items:
        tnn = str(item["tnn"]).upper()
        grams = item.get("grams")
        if grams is None:
            inv.pop(tnn, None)
        else:
            inv[tnn] = round(float(grams), 1)
    settings["inventory"] = inv
    p.settings = settings
    await db.commit()
    return {"ok": True, "inventory": inv}


class SelectSlotBody(BaseModel):
    tnn: str          # 如 T1A(盒子T1 料道A)


@router.post("/{printer_id}/select-slot")
async def select_slot(printer_id: int, body: SelectSlotBody,
                      db: AsyncSession = Depends(get_db),
                      user: User = Depends(current_user)):
    """自动换料到指定 CFS 料道(与打印机屏幕「进料」同一宏链,约 20-60 秒)。"""
    p = await db.get(Printer, printer_id)
    if p is None or p.user_id != user.id:
        raise HTTPException(404, "打印机不存在")
    adapter = build_adapter(p)
    try:
        return await adapter.select_slot(body.tnn)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(502, str(exc)) from exc
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
