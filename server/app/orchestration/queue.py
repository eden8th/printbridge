"""任务队列:进程内单 worker(自托管单用户形态,无需外部队列)。"""
from __future__ import annotations

import asyncio


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
        """投递任务(同步方法,调用点无需 await)。"""
        self._q.put_nowait(job_id)

    async def _worker_loop(self) -> None:
        from app.orchestration.runner import execute_job
        while True:
            job_id = await self._q.get()
            try:
                await execute_job(job_id)
            except asyncio.CancelledError:
                raise
            except Exception as exc:  # worker 不允许因单任务崩溃
                print(f"[job-worker] job {job_id} crashed: {exc!r}")
            finally:
                self._q.task_done()


queue = JobQueue()