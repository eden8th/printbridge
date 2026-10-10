"""应用设置:全局键值(AppSetting)+ 本地单用户保证。"""
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import AppSetting, User


async def get_setting(db: AsyncSession, key: str) -> dict:
    row = await db.get(AppSetting, key)
    return dict(row.value) if row else {}


async def put_setting(db: AsyncSession, key: str, value: dict) -> None:
    row = await db.get(AppSetting, key)
    if row:
        row.value = value
    else:
        db.add(AppSetting(key=key, value=value))
    await db.commit()


async def get_makerworld_cfg(db: AsyncSession) -> dict:
    return await get_setting(db, "makerworld")


async def put_makerworld_cfg(db: AsyncSession, value: dict) -> None:
    return await put_setting(db, "makerworld", value)


async def get_local_user(db: AsyncSession) -> User:
    """自动创建并返回唯一的本地用户(user_id 贯穿所有表)。"""
    res = await db.execute(select(User).where(User.is_local.is_(True)).limit(1))
    user = res.scalar_one_or_none()
    if user is None:
        user = User(username="local")
        db.add(user)
        await db.commit()
        await db.refresh(user)
    return user