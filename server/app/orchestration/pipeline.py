"""一键打印流水线:下载 → 切片 → 上传 → 启动打印,全程状态机 + 实时进度。

payload 约定(kind=pipeline / slice):
  source, design_id, instance_id      # 从模型源一键导入(会先入库)
  model_file_id                       # 直接指定库内已有文件(跳过下载)
  printer_id, bundle, machine_id, filament_ids, process_id, plate
  auto_start(bool, 默认 True)         # 上传后是否立即开始打印
  download_only(bool)                 # 只下载入库(模型库导入用)
  slice_only(bool)                    # 只切片入库(kind=slice 任务)

取消:各阶段之间检查 DB 中的 state,若已 cancelled 则终止。
"""
from __future__ import annotations

import time
import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from app.models import ModelFile, ModelRecord, Printer
from app.orchestration import jobs_service as jsvc
from app.printers import build_adapter
from app.slicing.orca_cli import SliceRequest, slice_model
from app.slicing.registry import resolve_paths
from app.services import storage
from app.sources import build_adapter as build_source


class PipelineError(Exception):
    pass


async def _check_cancelled(db: AsyncSession, job) -> bool:
    await db.refresh(job)
    return job.state == "cancelled"


async def _wait_nozzle_cool(db: AsyncSession, job, adapter, jsvc,
                            limit: float, timeout: float = 420.0) -> bool:
    """轮询喷嘴温度直到降到 limit 以下(供 START_PRINT 两级升温用)。

    读不到温度(打印机离线等)时立即返回 True,不阻塞打印;用户取消则提前结束。
    """
    import asyncio as _asyncio
    waited = 0.0
    while waited < timeout:
        if await _check_cancelled(db, job):
            return False
        try:
            tel = await adapter.status()
            temp = tel.nozzle_temp
        except Exception:  # noqa: BLE001  状态读取失败不阻塞
            return True
        if temp is None or temp <= limit:
            return True
        await _asyncio.sleep(5.0)
        waited += 5.0
    return False


async def _download_stage(db: AsyncSession, job, payload: dict) -> ModelFile:
    """从模型源拉取指定实例并入库,返回 ModelFile。"""
    await jsvc.set_state(db, job, "downloading", "从模型源下载", 0.05)
    source = await build_source(str(payload["source"]), db, job.user_id)
    try:
        design = await source.design(str(payload["design_id"]))
        inst = next((i for i in design.instances
                     if i.instance_id == str(payload.get("instance_id", ""))),
                    design.instances[0] if design.instances else None)
        if inst is None:
            raise PipelineError("该设计没有可下载的实例")
        url, filename = await source.resolve_download(design, inst)

        record = ModelRecord(user_id=job.user_id, source=source.key,
                             source_design_id=design.id, title=design.title,
                             cover_url=design.cover, source_url=design.source_url,
                             author=design.author)
        db.add(record)
        await db.flush()

        rel = storage.rel_model(job.user_id, record.id, filename)
        abs_dest = str(storage.abs_path(rel))
        # P0 简化:整段下载完成后一次性更新进度(回调节流在 P1 优化)
        async for _ in source.download_stream(url, abs_dest):
            pass

        size = storage.abs_path(rel).stat().st_size
        file_row = ModelFile(model_id=record.id, user_id=job.user_id,
                             name=filename, path=rel, size=size,
                             kind=filename.rsplit(".", 1)[-1].lower(),
                             meta={"instance_id": inst.instance_id,
                                   "profile_id": inst.profile_id})
        db.add(file_row)
        await db.commit()
        await db.refresh(file_row)
        if not payload.get("download_only"):
            job.payload = {**payload, "model_file_id": file_row.id}
            await db.commit()
        await jsvc.set_state(db, job, "downloading", f"已下载 {design.title}", 0.35)
        return file_row
    finally:
        await source.aclose()


async def _slice_stage(db: AsyncSession, job, payload: dict, file_row: ModelFile):
    """切片并把产物移动到正式 G-code 目录,返回 (result, gcode相对路径)。"""
    import shutil as _shutil

    await jsvc.set_state(db, job, "slicing", "调用切片引擎", 0.4)
    from app.slicing import registry
    machine_ids, filament_paths, process_path = resolve_paths(
        payload["bundle"], payload["machine_id"],
        payload["filament_ids"], payload["process_id"])
    # 用户选色:生成覆盖 filament_colour 的耗材配置副本(参与 CFS 料道匹配)
    colors = payload.get("filament_colors") or []
    if any(c for c in colors):
        filament_paths = registry.prepare_filament_files(
            filament_paths, colors, storage.abs_path(f"tmp/slice_job{job.id}"))
    job.log_path = job.log_path or jsvc.log_path_for(job)
    await db.commit()
    work_dir = storage.abs_path(f"gcode/u{job.user_id}/job{job.id}_slice")
    result = await slice_model(SliceRequest(
        input_path=str(storage.abs_path(file_row.path)),
        output_dir=str(work_dir),
        machine_files=machine_ids,
        filament_files=filament_paths,
        process_file=process_path,
        plate=int(payload.get("plate") or 0),
        log_path=job.log_path,
    ), exe_path=payload.get("slicer_exe") or "")
    if not result.ok:
        raise PipelineError(result.error)
    if not result.gcode_path:
        raise PipelineError("切片完成但未找到 G-code 产物")

    # 把产物从 outputdir 移到正式位置(缩略图同移,容器与临时文件清理)
    final_rel = storage.rel_gcode(job.user_id, job.id, file_row.name)
    _shutil.move(result.gcode_path, storage.abs_path(final_rel))
    thumb_rel = ""
    if result.thumbnail_path:
        thumb_rel = f"gcode/u{job.user_id}/job{job.id}_thumb.png"
        _shutil.move(result.thumbnail_path, storage.abs_path(thumb_rel))
    _shutil.rmtree(work_dir, ignore_errors=True)
    await jsvc.set_state(
        db, job, "slicing",
        f"切片完成,预估 {int(result.estimated_sec // 60)} 分钟 / "
        f"{result.filament_grams:.0f} g", 0.75)
    return result, final_rel, thumb_rel


async def _mark_stage(db: AsyncSession, job, stages: dict, name: str, t0: float) -> None:
    """阶段耗时埋点:写入 job.result.stages,供任务统计聚合。"""
    stages[name] = round(time.monotonic() - t0, 1)
    job.result = {**(job.result or {}), "stages": dict(stages)}
    await db.commit()


async def run_pipeline(db: AsyncSession, job) -> dict:
    payload = job.payload or {}
    stages: dict = {}

    if payload.get("download_only"):
        await _download_stage(db, job, payload)
        if await _check_cancelled(db, job):
            return {}
        await jsvc.set_state(db, job, "done", "已入库", 1.0)
        return {}

    # 1) 模型文件
    file_row: ModelFile | None = None
    if payload.get("model_file_id"):
        file_row = await db.get(ModelFile, int(payload["model_file_id"]))
        if file_row is None or file_row.user_id != job.user_id:
            raise PipelineError("模型文件不存在")
    else:
        t0 = time.monotonic()
        file_row = await _download_stage(db, job, payload)
        await _mark_stage(db, job, stages, "download", t0)
        if await _check_cancelled(db, job):
            return {}

    # 2) 库内 G-code 直接推送打印(模型库「推送打印」入口):跳过切片
    if payload.get("print_gcode"):
        out_rel = file_row.path
        thumb_rel = str((file_row.meta or {}).get("thumbnail_path") or "")
        result = None
    else:
        # 2) 切片
        t0 = time.monotonic()
        result, out_rel, thumb_rel = await _slice_stage(db, job, payload, file_row)
        await _mark_stage(db, job, stages, "slice", t0)
        if await _check_cancelled(db, job):
            return {}

    if payload.get("slice_only"):
        # 切片产物入库(kind=gcode),供后续手动推送;封面用切片任务缩略图
        record = ModelRecord(user_id=job.user_id, source="sliced",
                             source_design_id=str(job.id),
                             title=f"{file_row.name} (切片产物)",
                             cover_url=f"/api/jobs/{job.id}/thumbnail")
        db.add(record)
        await db.flush()
        g = ModelFile(model_id=record.id, user_id=job.user_id,
                      name=storage.safe_name(f"{file_row.name}.gcode"),
                      path=out_rel, size=storage.abs_path(out_rel).stat().st_size,
                      kind="gcode",
                      meta={"estimated_sec": result.estimated_sec,
                            "filament_grams": result.filament_grams,
                            "thumbnail_path": thumb_rel,
                            "job_id": job.id})
        db.add(g)
        await db.commit()
        await jsvc.set_state(db, job, "done", "切片产物已入库", 1.0)
        return {"gcode_path": out_rel, "gcode_file_id": g.id,
                "thumbnail_path": thumb_rel}

    # 3) 上传 + 打印
    t0 = time.monotonic()
    await jsvc.set_state(db, job, "uploading", "上传 G-code 到打印机", 0.8)
    printer = await db.get(Printer, job.printer_id)
    if printer is None or printer.user_id != job.user_id:
        raise PipelineError("打印机不存在")
    # 库存校验:选定料道记录了库存且低于本件克重时提前拦截(切片后即知克重)
    grams = result.filament_grams if result else float((file_row.meta or {}).get("filament_grams") or 0)
    tnn = str(payload.get("cfs_tnn") or "").strip().upper()
    inv = (printer.settings or {}).get("inventory") or {}
    if tnn and grams and tnn in inv and grams > float(inv[tnn]):
        raise PipelineError(
            f"料道 {tnn} 库存不足:本件约需 {grams:.0f}g,仅记录 {float(inv[tnn]):.0f}g。"
            "请更换料道/补充耗材,或在配置弹层修正库存后重试")
    adapter = build_adapter(printer)
    remote = ""
    try:
        remote_name = f"printbridge_{uuid.uuid4().hex[:8]}.gcode"
        remote = await adapter.send_file(str(storage.abs_path(out_rel)), remote_name)
        await jsvc.set_state(db, job, "uploading", "上传完成", 0.95)
        if payload.get("auto_start", True):
            # 上次打印若触发加热看门狗等故障,klippy 会锁死在 shutdown,
            # 所有 G-code 被拒;先检测并自动恢复(firmware_restart)
            st = await adapter.ensure_ready()
            if st != "ready":
                jsvc.append_log(job, f"[打印] 打印机状态 {st},尝试继续")
        # CFS 自动换料:用户选了料道时,启动打印前先切换(与屏幕「进料」同一宏链)
        tnn = str(payload.get("cfs_tnn") or "").strip().upper()
        if tnn and payload.get("auto_start", True):
            await jsvc.set_state(db, job, "uploading",
                                 f"切换 CFS 料道 {tnn}(约 20-60 秒)", 0.97)
            switched = False
            try:
                await adapter.select_slot(tnn)
                switched = True
                jsvc.append_log(job, f"[CFS] 已切换到料道 {tnn}")
            except Exception as exc:  # noqa: BLE001  换料失败不阻塞打印
                jsvc.append_log(job, f"[CFS] 料道切换失败:{exc}")
            if switched:
                # 换料宏会把喷嘴烧到打印温度(如 PETG 250°C)且结束时不关加热,
                # 而 K2 的 START_PRINT 是两级升温(140→180→目标),喷嘴远热于
                # 目标时固件加热看门狗(verify_heater check_gain_time=60s)会因
                # “温度不升”误判故障中止打印(key564)。先关加热并等喷嘴降到
                # 一阶预热温度以下再开打,让升温呈正常上升曲线(约 1-2 分钟)。
                await jsvc.set_state(db, job, "uploading",
                                     "等待喷嘴降温(换料后),避免升温看门狗误判", 0.97)
                try:
                    await adapter.run_gcode("M104 S0")   # 关喷嘴加热,配合降温
                except Exception:  # noqa: BLE001
                    pass
                if not await _wait_nozzle_cool(db, job, adapter, jsvc, limit=135.0):
                    jsvc.append_log(job, "[CFS] 喷嘴降温等待超时,仍尝试开始打印")
        if payload.get("auto_start", True):
            await adapter.start_print(remote)
            # 跟踪打印最终结果(klippy_shutdown/error/completed),写回任务详情
            from app.services.print_watch import start_watcher
            start_watcher(job.id, printer.id, remote)
    finally:
        if hasattr(adapter, "aclose"):
            await adapter.aclose()

    await _mark_stage(db, job, stages, "upload", t0)
    if payload.get("auto_start", True):
        await jsvc.set_state(db, job, "done",
                             "已发送打印指令,可在打印机页观察进度", 1.0)
    else:
        await jsvc.set_state(db, job, "done",
                             "已上传到打印机(未自动开始),可到打印机页选择文件开始", 1.0)
    meta = file_row.meta or {}
    return {"gcode_path": out_rel, "remote_file": remote,
            "thumbnail_path": thumb_rel,
            "estimated_sec": result.estimated_sec if result else meta.get("estimated_sec", 0),
            "filament_grams": result.filament_grams if result else meta.get("filament_grams", 0)}
