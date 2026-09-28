"""模型源(搜索/详情)+ 我的模型库(导入/列表/删除/文件下载)。"""
from __future__ import annotations

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.api.deps import current_user, get_db
from app.core.events import bus
from app.models import ModelFile, ModelRecord, User
from app.orchestration import jobs_service as jsvc
from app.orchestration.queue import queue
from app.services import storage
from app.services.settings_service import get_setting
from app.sources import build_adapter, source_keys

router = APIRouter(prefix="/api", tags=["market"])


# ---- 模型源 ------------------------------------------------------------
@router.get("/sources")
async def list_sources():
    return [{"key": k, "name": n} for k, n in
            [("makerworld", "MakerWorld(拓竹)")]]


@router.get("/sources/{key}/search")
async def search_models(key: str, keyword: str, page: int = 1,
                        page_size: int = 20, sort: str = "score",
                        db: AsyncSession = Depends(get_db),
                        user: User = Depends(current_user)):
    adapter = await build_adapter(key, db)
    try:
        total, items = await adapter.search(keyword, page, page_size, sort)
        return {"total": total, "items": [it.__dict__ for it in items]}
    finally:
        await adapter.aclose()


@router.get("/sources/{key}/design/{design_id}")
async def design_detail(key: str, design_id: str,
                        db: AsyncSession = Depends(get_db),
                        user: User = Depends(current_user)):
    adapter = await build_adapter(key, db)
    try:
        d = await adapter.design(design_id)
        return {"id": d.id, "title": d.title, "cover": d.cover,
                "author": d.author, "summary_html": d.summary_html,
                "source_url": d.source_url,
                "instances": [i.__dict__ for i in d.instances]}
    finally:
        await adapter.aclose()


# ---- 模型库 ------------------------------------------------------------
class ImportBody(BaseModel):
    source: str
    design_id: str
    instance_ids: list[str] = []   # 空 = 全部实例


@router.post("/library/import")
async def import_design(body: ImportBody, db: AsyncSession = Depends(get_db),
                        user: User = Depends(current_user)):
    """把源站设计的指定实例加入下载队列(下载完成后出现在模型库)。"""
    if not body.instance_ids:
        adapter = await build_adapter(body.source, db)
        try:
            d = await adapter.design(body.design_id)
            body.instance_ids = [i.instance_id for i in d.instances]
        finally:
            await adapter.aclose()
    created = []
    for iid in body.instance_ids:
        job = await jsvc.create_job(
            db, user.id, kind="pipeline",
            payload={"source": body.source, "design_id": body.design_id,
                     "instance_id": iid, "download_only": True},
        )
        queue.enqueue(job.id)
        created.append(job.id)
    return {"jobs": created}


@router.get("/library")
async def list_library(db: AsyncSession = Depends(get_db),
                       user: User = Depends(current_user)):
    res = await db.execute(
        select(ModelRecord).where(ModelRecord.user_id == user.id)
        .options(selectinload(ModelRecord.files))
        .order_by(ModelRecord.created_at.desc()))
    return [{
        "id": m.id, "title": m.title, "cover": m.cover_url,
        "source": m.source, "source_url": m.source_url, "author": m.author,
        "created_at": m.created_at.isoformat(),
        "files": [{"id": f.id, "name": f.name, "size": f.size,
                   "kind": f.kind, "meta": f.meta} for f in m.files],
    } for m in res.scalars()]


@router.get("/library/files/{file_id}/download")
async def download_file(file_id: int, db: AsyncSession = Depends(get_db),
                        user: User = Depends(current_user)):
    f = await db.get(ModelFile, file_id)
    if f is None or f.user_id != user.id:
        raise HTTPException(404, "文件不存在")
    return FileResponse(str(storage.abs_path(f.path)), filename=f.name)


@router.delete("/library/{model_id}")
async def delete_model(model_id: int, db: AsyncSession = Depends(get_db),
                       user: User = Depends(current_user)):
    res = await db.execute(
        select(ModelRecord).where(ModelRecord.id == model_id,
                                  ModelRecord.user_id == user.id)
        .options(selectinload(ModelRecord.files)))
    m = res.scalar_one_or_none()
    if m is None:
        raise HTTPException(404, "模型不存在")
    for f in m.files:  # 删除磁盘文件
        try:
            storage.abs_path(f.path).unlink(missing_ok=True)
        except OSError:
            pass
    await db.delete(m)
    await db.commit()
    await bus.publish("library_update", {"deleted": model_id})
    return {"ok": True}


class LibraryBatchDeleteBody(BaseModel):
    ids: list[int]


@router.post("/library/batch-delete")
async def batch_delete_models(body: LibraryBatchDeleteBody,
                              db: AsyncSession = Depends(get_db),
                              user: User = Depends(current_user)):
    """批量删除模型(含磁盘文件)。"""
    if not body.ids:
        return {"deleted": 0}
    res = await db.execute(
        select(ModelRecord).where(ModelRecord.id.in_(body.ids),
                                  ModelRecord.user_id == user.id)
        .options(selectinload(ModelRecord.files)))
    records = res.scalars().all()
    for m in records:
        for f in m.files:
            try:
                storage.abs_path(f.path).unlink(missing_ok=True)
            except OSError:
                pass
        await db.delete(m)
    await db.commit()
    if deleted_ids := [m.id for m in records]:
        await bus.publish("library_update", {"deleted": deleted_ids})
    return {"deleted": len(deleted_ids)}


class UploadBody(BaseModel):
    name: str = ""


@router.post("/library/upload")
async def upload_local(file: UploadFile = File(...),
                       db: AsyncSession = Depends(get_db),
                       user: User = Depends(current_user)):
    """本机已有 3MF/STL 上传入库。"""
    name = storage.safe_name(file.filename or "model.3mf")
    record = ModelRecord(user_id=user.id, source="upload",
                         source_design_id=name, title=name)
    db.add(record)
    await db.flush()
    rel = storage.rel_model(user.id, record.id, name)
    dest = storage.abs_path(rel)
    size = 0
    with open(dest, "wb") as fh:
        while chunk := await file.read(1024 * 512):
            fh.write(chunk)
            size += len(chunk)
    mf = ModelFile(model_id=record.id, user_id=user.id, name=name,
                   path=rel, size=size, kind=name.rsplit(".", 1)[-1].lower())
    db.add(mf)
    await db.commit()
    return {"model_id": record.id, "file_id": mf.id}
