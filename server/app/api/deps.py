"""API 依赖:DB 会话 + 当前用户。

自托管单用户形态,没有登录 —— 恒返回本地用户(首次访问时自动创建)。
user_id 依赖仍在各处传递:业务表的存储路径以它为一级目录,单用户下恒为 1。
"""
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