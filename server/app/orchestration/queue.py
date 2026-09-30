"""进程内任务队列。单实例足够;接口保持稳定,便于未来替换实现。"""
from __future__ import annotations

import asyncio

from app.core.db import SessionLocal
from app.core.events import bus
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
                result = await run_pipeline(db, job)
                if result:
                    job.result = {**(job.result or {}), **result}
                    await db.commit()
                    await bus.publish("job_update", {
                        "id": job.id, "kind": job.kind, "state": job.state,
                        "detail": job.detail, "progress": job.progress,
                        "error": job.error, "result": job.result,
                    })
            except SourceAuthError as exc:
                # 用户可自行解决的凭证问题:直接透传指引文案,不标"内部错误"
                await job_fetch_and_fail(db, job_id, str(exc))
            except SourceError as exc:
                await job_fetch_and_fail(db, job_id, f"模型源错误:{exc}")
            except PipelineError as exc:
                await job_fetch_and_fail(db, job_id, str(exc))
            except Exception as exc:
                await job_fetch_and_fail(db, job_id, f"内部错误:{exc!r}")


def _friendly_error(message: str) -> str:
    """原始异常 → 用户可读文案。原始信息始终写入任务日志([原始错误])。"""
    s = str(message)
    low = s.lower()
    if "key564" in s or ("not heating" in low and "heater" in low):
        return ("打印机上次打印故障未完全恢复(加热看门狗锁死)。系统已尝试自动恢复,"
                "若再次失败请重启打印机后重试")
    if "连接失败" in s or "timeout" in low or "timed out" in low:
        return "连接打印机失败:请确认打印机已开机联网、IP/端口正确"
    if "上传" in s and ("失败" in s or "拒绝" in s):
        return "G-code 上传失败:请确认打印机在线且剩余存储充足"
    if "指令被拒绝" in s or "被打印机拒绝" in s:
        if "料道" in s or "TNN" in s or "tnn" in s:
            return "CFS 换料失败:请确认所选料道已装料、打印机在线且无故障"
        return "打印机拒绝了指令:请确认打印机无故障提示、且不在其他任务中"
    if "凭证" in s or "token" in low:
        return "模型源凭证无效或过期:请到「设置」页更新后重试"
    if "切片失败" in s or "切片器" in s or "未找到 OrcaSlicer" in s:
        return f"切片失败:{s[:180]}"
    if "模型文件不存在" in s or "打印机不存在" in s:
        return s
    if "内部错误" in s:
        return "内部错误,请到任务详情复制日志反馈排查"
    return s[:200]


async def job_fetch_and_fail(db, job_id: int, message: str) -> None:
    from app.orchestration import jobs_service as jsvc
    job = await db.get(Job, job_id)
    if job and job.state not in ("cancelled",):
        job.log_path = job.log_path or jsvc.log_path_for(job)
        await db.commit()
        jsvc.append_log(job, f"[原始错误] {message}")
        await jsvc.set_state(db, job, "failed", error=_friendly_error(message))


queue = JobQueue()
