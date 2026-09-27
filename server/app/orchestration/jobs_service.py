"""任务服务:创建/状态流转/日志,状态变更即时推送到前端。"""
from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.events import bus
from app.models import Job
from app.services import storage


async def create_job(db: AsyncSession, user_id: int, kind: str,
                     payload: dict, printer_id: int | None = None,
                     model_file_id: int | None = None,
                     parent_id: int | None = None) -> Job:
    job = Job(user_id=user_id, kind=kind, state="queued", payload=payload,
              printer_id=printer_id, model_file_id=model_file_id,
              parent_id=parent_id)
    db.add(job)
    await db.commit()
    await db.refresh(job)
    await _emit(job)
    return job


async def set_state(db: AsyncSession, job: Job, state: str,
                    detail: str = "", progress: float | None = None,
                    error: str | None = None) -> None:
    job.state = state
    if detail:
        job.detail = detail
    if progress is not None:
        job.progress = max(0.0, min(1.0, progress))
    if error is not None:
        job.error = error
    await db.commit()
    await db.refresh(job)
    await _emit(job)


def log_path_for(job: Job) -> str:
    rel = storage.rel_log(job.user_id, job.id)
    storage.abs_path(rel)
    return str(storage.abs_path(rel))


def append_log(job: Job, line: str) -> None:
    if not job.log_path:
        return
    with open(job.log_path, "a", encoding="utf-8") as fh:
        fh.write(line.rstrip() + "\n")


async def _emit(job: Job) -> None:
    await bus.publish("job_update", {
        "id": job.id, "kind": job.kind, "state": job.state,
        "detail": job.detail, "progress": job.progress,
        "error": job.error, "model_file_id": job.model_file_id,
        "printer_id": job.printer_id, "parent_id": job.parent_id,
        "result": job.result,
    })
