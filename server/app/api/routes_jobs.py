"""任务(一键打印/切片)与设置/参数包。"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import current_user, get_db
from app.core.events import bus
from app.models import Job, ModelFile, Printer, User
from app.orchestration import jobs_service as jsvc
from app.orchestration.queue import queue
from app.slicing import detect_slicer
from app.services.settings_service import get_setting, put_setting

router = APIRouter(prefix="/api", tags=["jobs"])


class OneClickBody(BaseModel):
    # 来源二选一
    source: str | None = None
    design_id: str | None = None
    instance_id: str | None = None
    model_file_id: int | None = None
    # 打印目标与切片参数
    printer_id: int
    bundle: str
    machine_id: str
    filament_ids: list[str]
    filament_colors: list[str] = []
    process_id: str
    plate: int | None = None
    auto_start: bool = True
    cfs_tnn: str | None = None        # CFS 料道(如 T1A),打印前自动换料


@router.post("/jobs/oneclick")
async def oneclick(body: OneClickBody, db: AsyncSession = Depends(get_db),
                   user: User = Depends(current_user)):
    """核心接口:搜索页点「一键打印」即调这里。"""
    if not body.model_file_id and not (body.source and body.design_id):
        raise HTTPException(400, "需要 model_file_id 或 source+design_id")
    printer = await db.get(Printer, body.printer_id)
    if printer is None or printer.user_id != user.id:
        raise HTTPException(404, "打印机不存在")
    # 切片参数记忆:按打印机记住本次配置,下次打开配置弹层自动填充
    settings = dict(printer.settings or {})
    settings["last_print"] = {
        "bundle": body.bundle,
        "machine_id": body.machine_id,
        "filament_ids": body.filament_ids,
        "filament_colors": body.filament_colors,
        "process_id": body.process_id,
        "cfs_tnn": body.cfs_tnn,
    }
    printer.settings = settings
    await db.commit()
    job = await jsvc.create_job(
        db, user.id, kind="pipeline", printer_id=body.printer_id,
        model_file_id=body.model_file_id,
        payload=body.model_dump(exclude_none=True))
    queue.enqueue(job.id)
    return {"job_id": job.id}


class SliceOnlyBody(BaseModel):
    file_id: int
    bundle: str
    machine_id: str
    filament_ids: list[str]
    filament_colors: list[str] = []
    process_id: str
    plate: int | None = None
    cfs_tnn: str | None = None


@router.post("/jobs/slice")
async def slice_only(body: SliceOnlyBody, db: AsyncSession = Depends(get_db),
                     user: User = Depends(current_user)):
    """只切片不打印(产物进模型库,可再手动推打印)。"""
    f = await db.get(ModelFile, body.file_id)
    if f is None or f.user_id != user.id:
        raise HTTPException(404, "文件不存在")
    payload = {"slice_only": True, "model_file_id": body.file_id,
               **body.model_dump(exclude_none=True, exclude={"file_id"})}
    job = await jsvc.create_job(
        db, user.id, kind="slice", model_file_id=body.file_id,
        payload=payload)
    queue.enqueue(job.id)
    return {"job_id": job.id}


@router.get("/jobs")
async def list_jobs(limit: int = 50, db: AsyncSession = Depends(get_db),
                    user: User = Depends(current_user)):
    res = await db.execute(
        select(Job).where(Job.user_id == user.id)
        .order_by(Job.id.desc()).limit(min(limit, 200)))
    return [{"id": j.id, "kind": j.kind, "state": j.state, "detail": j.detail,
             "progress": j.progress, "error": j.error,
             "retries": int((j.payload or {}).get("retries") or 0),
             "model_file_id": j.model_file_id, "printer_id": j.printer_id,
             "payload": j.payload, "result": j.result,
             "created_at": j.created_at.isoformat()} for j in res.scalars()]


class PrintGcodeBody(BaseModel):
    file_id: int
    printer_id: int
    cfs_tnn: str | None = None
    auto_start: bool = True


@router.post("/jobs/print-gcode")
async def print_gcode(body: PrintGcodeBody, db: AsyncSession = Depends(get_db),
                      user: User = Depends(current_user)):
    """库内 G-code 直接推送打印(模型库切片产物/已有 G-code,跳过切片)。"""
    f = await db.get(ModelFile, body.file_id)
    if f is None or f.user_id != user.id or f.kind != "gcode":
        raise HTTPException(404, "G-code 文件不存在")
    printer = await db.get(Printer, body.printer_id)
    if printer is None or printer.user_id != user.id:
        raise HTTPException(404, "打印机不存在")
    payload = {"print_gcode": True, "model_file_id": f.id,
               "printer_id": body.printer_id, "auto_start": body.auto_start}
    if body.cfs_tnn:
        payload["cfs_tnn"] = body.cfs_tnn
    job = await jsvc.create_job(
        db, user.id, kind="print", printer_id=body.printer_id,
        model_file_id=f.id, payload=payload)
    queue.enqueue(job.id)
    return {"job_id": job.id}


@router.get("/jobs/stats")
async def job_stats(db: AsyncSession = Depends(get_db),
                    user: User = Depends(current_user)):
    """任务使用统计(北极星:成功打印次数)。"""
    res = await db.execute(select(Job).where(Job.user_id == user.id))
    jobs = res.scalars().all()
    total = len(jobs)
    done = [j for j in jobs if j.state == "done"]
    failed = [j for j in jobs if j.state == "failed"]
    printed = [j for j in jobs if (j.result or {}).get("print_status") == "completed"]
    slice_secs = [v for j in jobs
                  if (v := (j.result or {}).get("stages", {}).get("slice")) is not None]
    return {
        "total": total,
        "done": len(done),
        "failed": len(failed),
        "success_rate": round(len(done) / total * 100) if total else None,
        "prints_completed": len(printed),
        "avg_slice_sec": round(sum(slice_secs) / len(slice_secs), 1) if slice_secs else None,
    }


@router.get("/jobs/{job_id}")
async def job_detail(job_id: int, db: AsyncSession = Depends(get_db),
                     user: User = Depends(current_user)):
    """任务详情(含模型/打印机名称富化)。"""
    j = await db.get(Job, job_id)
    if j is None or j.user_id != user.id:
        raise HTTPException(404, "任务不存在")
    model_file_name = printer_name = None
    if j.model_file_id:
        f = await db.get(ModelFile, j.model_file_id)
        model_file_name = f.name if f else None
    if j.printer_id:
        p = await db.get(Printer, j.printer_id)
        printer_name = p.name if p else None
    return {
        "id": j.id, "kind": j.kind, "state": j.state, "detail": j.detail,
        "progress": j.progress, "error": j.error, "payload": j.payload,
        "retries": int((j.payload or {}).get("retries") or 0),
        "result": j.result, "model_file_id": j.model_file_id,
        "model_file_name": model_file_name, "printer_id": j.printer_id,
        "printer_name": printer_name, "has_log": bool(j.log_path),
        "created_at": j.created_at.isoformat(),
        "updated_at": j.updated_at.isoformat(),
    }


@router.delete("/jobs/{job_id}")
async def delete_job(job_id: int, db: AsyncSession = Depends(get_db),
                     user: User = Depends(current_user)):
    """删除任务(仅限已结束的任务;进行中的请先取消)。"""
    from pathlib import Path
    j = await db.get(Job, job_id)
    if j is None or j.user_id != user.id:
        raise HTTPException(404, "任务不存在")
    if j.state not in ("done", "failed", "cancelled"):
        raise HTTPException(400, "任务仍在进行中,请先取消再删除")
    if j.log_path:
        Path(j.log_path).unlink(missing_ok=True)
    await db.delete(j)
    await db.commit()
    await bus.publish("job_deleted", {"id": job_id})
    return {"ok": True}


@router.get("/jobs/{job_id}/log")
async def job_log(job_id: int, db: AsyncSession = Depends(get_db),
                  user: User = Depends(current_user)):
    from app.services import storage
    j = await db.get(Job, job_id)
    if j is None or j.user_id != user.id:
        raise HTTPException(404, "任务不存在")
    if not j.log_path:
        return {"log": ""}
    from pathlib import Path
    p = Path(j.log_path)
    return {"log": p.read_text(encoding="utf-8", errors="replace")[-8000:]
            if p.is_file() else ""}


@router.get("/jobs/{job_id}/thumbnail")
async def job_thumbnail(job_id: int, db: AsyncSession = Depends(get_db),
                        user: User = Depends(current_user)):
    """打印物品缩略图(切片板预览)。"""
    from pathlib import Path
    from fastapi.responses import FileResponse as _FR
    from app.services import storage
    j = await db.get(Job, job_id)
    if j is None or j.user_id != user.id:
        raise HTTPException(404, "任务不存在")
    rel = str((j.result or {}).get("thumbnail_path") or "")
    if not rel:
        raise HTTPException(404, "该任务没有缩略图")
    p = storage.abs_path(rel)
    if not p.is_file():
        raise HTTPException(404, "缩略图已被清理")
    return _FR(str(p), media_type="image/png")


class BatchDeleteBody(BaseModel):
    ids: list[int]


@router.post("/jobs/batch-delete")
async def batch_delete_jobs(body: BatchDeleteBody,
                            db: AsyncSession = Depends(get_db),
                            user: User = Depends(current_user)):
    """批量删除任务(仅限已结束的任务;进行中的跳过并计数)。"""
    from pathlib import Path
    deleted_ids = []
    skipped = 0
    for jid in body.ids:
        j = await db.get(Job, jid)
        if j is None or j.user_id != user.id:
            continue
        if j.state not in ("done", "failed", "cancelled"):
            skipped += 1
            continue
        if j.log_path:
            Path(j.log_path).unlink(missing_ok=True)
        await db.delete(j)
        deleted_ids.append(jid)
    await db.commit()
    if deleted_ids:
        await bus.publish("jobs_batch_deleted", {"ids": deleted_ids})
    return {"deleted": len(deleted_ids), "skipped": skipped}


@router.get("/jobs/{job_id}/gcode")
async def job_gcode(job_id: int, db: AsyncSession = Depends(get_db),
                    user: User = Depends(current_user)):
    """下载该任务切片产出的 G-code(打印类任务的产物不在模型库里)。"""
    from pathlib import Path
    from fastapi.responses import FileResponse as _FR
    from app.services import storage
    j = await db.get(Job, job_id)
    if j is None or j.user_id != user.id:
        raise HTTPException(404, "任务不存在")
    rel = str((j.result or {}).get("gcode_path") or "")
    if not rel:
        raise HTTPException(404, "该任务没有 G-code 产物")
    p = storage.abs_path(rel)
    if not p.is_file():
        raise HTTPException(404, "产物文件已被清理")
    return _FR(str(p), filename=p.name)


@router.post("/jobs/{job_id}/cancel")
async def cancel_job(job_id: int, db: AsyncSession = Depends(get_db),
                     user: User = Depends(current_user)):
    j = await db.get(Job, job_id)
    if j is None or j.user_id != user.id:
        raise HTTPException(404, "任务不存在")
    if j.state in ("done", "failed", "cancelled"):
        return {"ok": True, "state": j.state}
    await jsvc.set_state(db, j, "cancelled", error="用户取消")
    return {"ok": True}


@router.post("/jobs/{job_id}/retry")
async def retry_job(job_id: int, db: AsyncSession = Depends(get_db),
                    user: User = Depends(current_user)):
    """重试失败/已取消的任务:复位状态重新入队。

    payload 快照里带着全部入参,下载阶段已成功过的任务带 model_file_id,
    重试会跳过下载直接切片,不会重复拉取模型。
    """
    j = await db.get(Job, job_id)
    if j is None or j.user_id != user.id:
        raise HTTPException(404, "任务不存在")
    if j.state not in ("failed", "cancelled"):
        raise HTTPException(400, "只有失败或已取消的任务可以重试")
    payload = dict(j.payload or {})
    retries = int(payload.get("retries") or 0) + 1
    payload["retries"] = retries
    j.payload = payload
    await jsvc.set_state(db, j, "queued", detail="重试:已重新入队",
                         progress=0.0, error="")
    queue.enqueue(j.id)
    return {"ok": True, "retries": retries}


@router.post("/jobs/{job_id}/reprint")
async def reprint_job(job_id: int, db: AsyncSession = Depends(get_db),
                      user: User = Depends(current_user)):
    """重新打印:用已完成任务的入参快照创建一个新任务并入队。

    与 retry 的区别:retry 复位原任务重跑(仅限 failed/cancelled);
    reprint 面向 done 任务,生成一条全新任务记录,原任务历史保留。
    """
    j = await db.get(Job, job_id)
    if j is None or j.user_id != user.id:
        raise HTTPException(404, "任务不存在")
    p = dict(j.payload or {})
    if j.kind != "pipeline" or p.get("slice_only") or p.get("download_only"):
        raise HTTPException(400, "只有一键打印任务支持重新打印")
    model_file_id = p.get("model_file_id")
    if not model_file_id and not (p.get("source") and p.get("design_id")):
        raise HTTPException(400, "任务入参缺少模型信息,无法重新打印")
    if not p.get("printer_id"):
        raise HTTPException(400, "任务入参缺少打印机,无法重新打印")
    body = {k: p[k] for k in (
        "source", "design_id", "instance_id", "bundle", "machine_id",
        "filament_ids", "filament_colors", "process_id", "plate", "cfs_tnn")
        if p.get(k) not in (None, "", [])}
    if model_file_id:
        body["model_file_id"] = int(model_file_id)
    body["printer_id"] = int(p["printer_id"])
    body["auto_start"] = bool(p.get("auto_start", True))
    job = await jsvc.create_job(
        db, user.id, kind="pipeline", printer_id=body["printer_id"],
        model_file_id=body.get("model_file_id"),
        payload=body)
    queue.enqueue(job.id)
    return {"job_id": job.id}


# ---- 切片参数包 --------------------------------------------------------
@router.get("/profiles")
async def profiles():
    """机型列表(轻量):100+ 机型的耗材/工艺按需经 /profiles/{key}/options 拉取。"""
    from app.slicing.registry import list_bundles
    return [{"key": b.key, "name": b.name,
             "nozzles": [{"nozzle": n.nozzle, "machine_id": n.machine_id}
                         for n in b.nozzles]}
            for b in list_bundles()]


@router.get("/profiles/{key}/options")
async def profile_options(key: str, nozzle: str = "0.4"):
    """指定机型+喷嘴的耗材/工艺列表。"""
    from app.slicing.registry import get_bundle
    try:
        b = get_bundle(key)
    except FileNotFoundError as exc:
        raise HTTPException(404, str(exc)) from exc
    return {
        "nozzle": nozzle,
        "filaments": [{"id": f.id, "name": f.name, "type": f.ftype}
                      for f in b.filaments.get(nozzle, [])],
        "processes": [{"id": p.id, "name": p.name}
                      for p in b.processes.get(nozzle, [])],
    }


# ---- 设置 --------------------------------------------------------------
@router.get("/settings")
async def read_settings(db: AsyncSession = Depends(get_db),
                        user: User = Depends(current_user)):
    cfg = await get_setting(db, "app")
    mw = await get_setting(db, "makerworld")
    # token 只回传是否有值,不回传内容
    return {"app": cfg,
            "makerworld": {**mw, "token": "已配置" if mw.get("token") else ""}}


class SettingsBody(BaseModel):
    app: dict = {}
    makerworld: dict = {}


@router.put("/settings")
async def write_settings(body: SettingsBody,
                         db: AsyncSession = Depends(get_db),
                         user: User = Depends(current_user)):
    if body.app:
        await put_setting(db, "app", body.app)
    if body.makerworld:
        cur = await get_setting(db, "makerworld")
        new = {**cur, **body.makerworld}
        if body.makerworld.get("token") == "已配置":  # 前端原样回传 = 不修改
            new["token"] = cur.get("token", "")
        await put_setting(db, "makerworld", new)
    return {"ok": True}


@router.get("/settings/slicer-probe")
async def slicer_probe(db: AsyncSession = Depends(get_db),
                       user: User = Depends(current_user)):
    cfg = await get_setting(db, "app")
    path = detect_slicer(str(cfg.get("slicer_exe") or ""))
    return {"found": bool(path), "path": path}


class VerifyTokenBody(BaseModel):
    token: str


@router.post("/settings/verify-makerworld")
async def verify_makerworld(body: VerifyTokenBody):
    """校验 MakerWorld token 是否有效(设计详情接口带凭证自查)。"""
    import httpx
    token = (body.token or "").strip()
    if not token:
        return {"valid": False, "detail": "token 为空"}
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            r = await client.get(
                "https://api.bambulab.cn/v1/design-user-service/my/preference",
                headers={"Authorization": f"Bearer {token}",
                         "Referer": "https://makerworld.com/",
                         "User-Agent": "Mozilla/5.0"})
    except httpx.HTTPError as exc:
        return {"valid": None, "detail": f"网络错误,无法校验:{exc}"}
    if r.status_code == 200:
        return {"valid": True, "detail": "token 有效"}
    if r.status_code in (401, 403):
        return {"valid": False, "detail": "token 无效或已过期,请重新复制"}
    return {"valid": None, "detail": f"无法确认(HTTP {r.status_code}),仍可保存后试下载"}


class MakerWorldLoginBody(BaseModel):
    account: str
    password: str
    region: str = "cn"


@router.post("/settings/makerworld-login")
async def makerworld_login(body: MakerWorldLoginBody,
                           db: AsyncSession = Depends(get_db),
                           user: User = Depends(current_user)):
    """拓竹账号密码登录:调官方登录接口换 token 并自动保存。

    密码只在本请求内使用,不落盘;成功后仅保存 token。
    部分账号会触发邮箱验证码(MFA),此时提示用户改用书签/手动方式。
    """
    import httpx
    account = (body.account or "").strip()
    password = body.password or ""
    if not account or not password:
        return {"ok": False, "detail": "请填写账号和密码"}
    host = "api.bambulab.cn" if body.region == "cn" else "api.bambulab.com"
    try:
        async with httpx.AsyncClient(timeout=15) as client:
            r = await client.post(f"https://{host}/v1/user-service/user/login",
                                  json={"account": account, "password": password},
                                  headers={"User-Agent": "Mozilla/5.0"})
    except httpx.HTTPError as exc:
        return {"ok": None, "detail": f"网络错误:{exc}"}
    try:
        data = r.json()
    except ValueError:
        return {"ok": None, "detail": f"登录接口返回异常(HTTP {r.status_code})"}
    token = str(data.get("token") or data.get("accessToken") or "")
    if token:
        cur = await get_setting(db, "makerworld")
        await put_setting(db, "makerworld",
                          {**cur, "token": token, "region": body.region})
        return {"ok": True, "detail": "登录成功,凭证已自动保存"}
    err = str(data.get("error") or data.get("message") or "")
    if r.status_code in (401, 400) and "password" in err.lower() or "incorrect" in err.lower():
        return {"ok": False, "detail": "账号或密码错误"}
    if "verif" in err.lower() or "code" in err.lower():
        return {"ok": False, "detail":
                "该账号触发了邮箱验证码校验,请改用下方的书签提取或手动粘贴 token"}
    return {"ok": False, "detail": err or f"登录失败(HTTP {r.status_code})"}
