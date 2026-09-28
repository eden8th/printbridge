"""PrintBridge 服务端入口。

启动流程:建表 → 确保本地用户 → 启动任务队列 worker → 恢复打印机遥测循环。
"""
from __future__ import annotations

from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from sqlalchemy import select

from app.api import api_router
from app.core.config import settings
from app.core.db import SessionLocal, init_db
from app.models import Printer
from app.orchestration.queue import queue
from app.printers import manager
from app.services.settings_service import get_local_user


@asynccontextmanager
async def lifespan(app: FastAPI):
    await init_db()
    async with SessionLocal() as db:
        await get_local_user(db)
        res = await db.execute(select(Printer).where(Printer.is_enabled.is_(True)))
        printers = res.scalars().all()
    queue.start()
    for p in printers:      # 重启后恢复遥测循环
        manager.ensure_loop(p)
    yield
    await manager.shutdown()
    await queue.stop()
    from app.services.print_watch import cancel_all
    cancel_all()


app = FastAPI(title="PrintBridge", version="0.1.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"],
)

app.include_router(api_router)


@app.get("/api/health")
async def health():
    return {"ok": True, "role": settings.role}


# 生产模式:直接挂载前端构建产物(开发时前端走 Vite dev server)
# 用 SPA 回退路由而非 StaticFiles 挂载,保证 /search 等前端路由刷新不 404
_web_dist = Path(__file__).resolve().parents[2] / "web" / "dist"
if _web_dist.is_dir():
    from fastapi.responses import FileResponse

    @app.get("/{spa_path:path}", include_in_schema=False)
    async def spa_fallback(spa_path: str):
        candidate = (_web_dist / spa_path).resolve()
        if spa_path and str(candidate).startswith(str(_web_dist)) and candidate.is_file():
            return FileResponse(candidate)
        return FileResponse(_web_dist / "index.html")
