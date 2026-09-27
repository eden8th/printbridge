"""进程内任务队列。单实例足够;接口保持稳定,便于未来替换实现。"""
from __future__ import annotations

import asyncio

from app.core.db import SessionLocal
from app.models import Job
from app.orchestration.pipeline import PipelineError, run_pipeline
from app.sources.base import SourceAuthError, SourceError


class JobQueue:
    def __init__(self) -> None:
        self._q: asyncio.Queue[int] = asyncio.Queue()
        self._worker: asyncio.Task | None = None

    def start(self) -> None:
        if self._worker is None or self._worker.done():
            self._worker = asyncio.create_task(self._worker_loop(), name="job-worker")

    async def stop(self) -> None:
        if self._worker:
            self._worker.cancel()
            self._worker = None

    def enqueue(self, job_id: int) -> None:
        self._q.put_nowait(job_id)

    async def _worker_loop(self) -> None:
        while True:
            job_id = await self._q.get()
            try:
                await self._run_one(job_id)
            except asyncio.CancelledError:
                raise
            except Exception as exc:  # worker 不允许因单任务崩溃
                print(f"[job-worker] job {job_id} crashed: {exc!r}")
            finally:
                self._q.task_done()

    async def _run_one(self, job_id: int) -> None:
        async with SessionLocal() as db:
            job = await db.get(Job, job_id)
            if job is None or job.state not in ("queued",):
                return
            try:
                await run_pipeline(db, job)
            except SourceAuthError as exc:
                # 用户可自行解决的凭证问题:直接透传指引文案,不标"内部错误"
                await job_fetch_and_fail(db, job_id, str(exc))
            except SourceError as exc:
                await job_fetch_and_fail(db, job_id, f"模型源错误:{exc}")
            except PipelineError as exc:
                await job_fetch_and_fail(db, job_id, str(exc))
            except Exception as exc:
                await job_fetch_and_fail(db, job_id, f"内部错误:{exc!r}")


async def job_fetch_and_fail(db, job_id: int, message: str) -> None:
    from app.orchestration import jobs_service as jsvc
    job = await db.get(Job, job_id)
    if job and job.state not in ("cancelled",):
        job.log_path = job.log_path or jsvc.log_path_for(job)
        await db.commit()
        await jsvc.set_state(db, job, "failed", error=message)


queue = JobQueue()
