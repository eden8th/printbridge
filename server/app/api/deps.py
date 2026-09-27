"""API 依赖:DB 会话 + 本地用户(P0 无登录界面)。"""
from __future__ import annotations

from typing import AsyncIterator

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import SessionLocal
from app.models import User
from app.services.settings_service import get_local_user


async def get_db() -> AsyncIterator[AsyncSession]:
    async with SessionLocal() as session:
        yield session


async def current_user(db: AsyncSession = Depends(get_db)) -> User:
    return await get_local_user(db)
