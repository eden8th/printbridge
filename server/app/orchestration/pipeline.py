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


async def _download_stage(db: AsyncSession, job, payload: dict) -> ModelFile:
    """从模型源拉取指定实例并入库,返回 ModelFile。"""
    await jsvc.set_state(db, job, "downloading", "从模型源下载", 0.05)
    source = await build_source(str(payload["source"]), db)
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
    await jsvc.set_state(db, job, "slicing", "调用切片引擎", 0.4)
    machine_ids, filament_paths, process_path = resolve_paths(
        payload["bundle"], payload["machine_id"],
        payload["filament_ids"], payload["process_id"])
    out_rel = storage.rel_gcode(job.user_id, job.id, file_row.name)
    out_abs = str(storage.abs_path(out_rel))
    job.log_path = job.log_path or jsvc.log_path_for(job)
    await db.commit()
    result = await slice_model(SliceRequest(
        input_path=str(storage.abs_path(file_row.path)),
        output_gcode=out_abs,
        machine_files=machine_ids,
        filament_files=filament_paths,
        process_file=process_path,
        plate=payload.get("plate"),
        log_path=job.log_path,
    ), exe_path=payload.get("slicer_exe") or "")
    if not result.ok:
        raise PipelineError(result.error)
    await jsvc.set_state(
        db, job, "slicing",
        f"切片完成,预估 {int(result.estimated_sec // 60)} 分钟 / "
        f"{result.filament_grams:.0f} g", 0.75)
    return result, out_rel


async def run_pipeline(db: AsyncSession, job) -> dict:
    payload = job.payload or {}

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
        file_row = await _download_stage(db, job, payload)
        if await _check_cancelled(db, job):
            return {}

    # 2) 切片
    result, out_rel = await _slice_stage(db, job, payload, file_row)
    if await _check_cancelled(db, job):
        return {}

    if payload.get("slice_only"):
        # 切片产物入库(kind=gcode),供后续手动推送
        record = ModelRecord(user_id=job.user_id, source="sliced",
                             source_design_id=str(job.id),
                             title=f"{file_row.name} (切片产物)",
                             cover_url="")
        db.add(record)
        await db.flush()
        g = ModelFile(model_id=record.id, user_id=job.user_id,
                      name=storage.safe_name(f"{file_row.name}.gcode"),
                      path=out_rel, size=storage.abs_path(out_rel).stat().st_size,
                      kind="gcode",
                      meta={"estimated_sec": result.estimated_sec,
                            "filament_grams": result.filament_grams,
                            "job_id": job.id})
        db.add(g)
        await db.commit()
        await jsvc.set_state(db, job, "done", "切片产物已入库", 1.0)
        return {"gcode_path": out_rel, "gcode_file_id": g.id}

    # 3) 上传 + 打印
    await jsvc.set_state(db, job, "uploading", "上传 G-code 到打印机", 0.8)
    printer = await db.get(Printer, job.printer_id)
    if printer is None or printer.user_id != job.user_id:
        raise PipelineError("打印机不存在")
    adapter = build_adapter(printer)
    remote = ""
    try:
        remote_name = f"printbridge_{uuid.uuid4().hex[:8]}.gcode"
        remote = await adapter.send_file(str(storage.abs_path(out_rel)), remote_name)
        await jsvc.set_state(db, job, "uploading", "上传完成", 0.95)
        if payload.get("auto_start", True):
            await adapter.start_print(remote)
    finally:
        if hasattr(adapter, "aclose"):
            await adapter.aclose()

    await jsvc.set_state(db, job, "done",
                         "已发送打印指令,可在打印机页观察进度", 1.0)
    return {"gcode_path": out_rel, "remote_file": remote,
            "estimated_sec": result.estimated_sec,
            "filament_grams": result.filament_grams}
