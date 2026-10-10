"""数据模型。自托管单用户形态:全程只有 users 表里的一个 local 用户,
其余业务表保留 user_id 便于将来扩展,但不存在跨用户隔离逻辑。
"""
from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import JSON, BigInteger, DateTime, Float, ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.db import Base


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)
    username: Mapped[str] = mapped_column(String(64), unique=True)
    is_local: Mapped[bool] = mapped_column(default=True)  # 恒为本地单用户
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    models: Mapped[list["ModelRecord"]] = relationship(back_populates="user")
    printers: Mapped[list["Printer"]] = relationship(back_populates="user")


class ModelRecord(Base):
    """「我的模型库」条目:从某个模型源导入的一个设计。"""
    __tablename__ = "model_records"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    source: Mapped[str] = mapped_column(String(32))            # makerworld / printables / upload
    source_design_id: Mapped[str] = mapped_column(String(64))  # 源站设计 ID
    title: Mapped[str] = mapped_column(Text, default="")
    cover_url: Mapped[str] = mapped_column(Text, default="")
    source_url: Mapped[str] = mapped_column(Text, default="")
    author: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    user: Mapped[User] = relationship(back_populates="models")
    files: Mapped[list["ModelFile"]] = relationship(back_populates="model", cascade="all,delete-orphan")


class ModelFile(Base):
    """设计下的一个可打印文件(已下载到本地)。"""
    __tablename__ = "model_files"

    id: Mapped[int] = mapped_column(primary_key=True)
    model_id: Mapped[int] = mapped_column(ForeignKey("model_records.id"), index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    name: Mapped[str] = mapped_column(Text)
    path: Mapped[str] = mapped_column(Text)          # 相对 data_dir 的路径
    size: Mapped[int] = mapped_column(BigInteger, default=0)
    kind: Mapped[str] = mapped_column(String(16), default="3mf")  # 3mf / stl / other
    meta: Mapped[dict] = mapped_column(JSON, default=dict)        # 板位/图数等源信息
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    model: Mapped[ModelRecord] = relationship(back_populates="files")


class Printer(Base):
    """一台已注册的打印机。凭据明文存本地库(自托管单机,库文件不外传)。"""
    __tablename__ = "printers"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    name: Mapped[str] = mapped_column(String(128))
    adapter: Mapped[str] = mapped_column(String(32))   # creality_ws / moonraker
    host: Mapped[str] = mapped_column(String(128))
    port: Mapped[int | None] = mapped_column(nullable=True)       # None = 用适配器默认端口
    secret: Mapped[str] = mapped_column(Text, default="")         # API Key / FTP 密码等
    settings: Mapped[dict] = mapped_column(JSON, default=dict)    # 适配器私有配置(命令模板等)
    is_enabled: Mapped[bool] = mapped_column(default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    user: Mapped[User] = relationship(back_populates="printers")


class Job(Base):
    """统一任务表:pipeline(一键流水线)及其子步骤共用,父任务经 parent_id 关联。"""
    __tablename__ = "jobs"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    kind: Mapped[str] = mapped_column(String(16), index=True)     # pipeline/download/slice/print
    state: Mapped[str] = mapped_column(String(16), index=True, default="queued")
    # queued/running/done/failed/cancelled;pipeline 细化:
    # downloading/slicing/uploading/printing 由 state+detail 表达
    detail: Mapped[str] = mapped_column(String(32), default="")
    progress: Mapped[float] = mapped_column(Float, default=0.0)   # 0~1
    payload: Mapped[dict] = mapped_column(JSON, default=dict)     # 任务入参快照
    result: Mapped[dict] = mapped_column(JSON, default=dict)      # 产物信息(gcode 路径等)
    error: Mapped[str] = mapped_column(Text, default="")
    log_path: Mapped[str] = mapped_column(Text, default="")
    parent_id: Mapped[int | None] = mapped_column(ForeignKey("jobs.id"), nullable=True)
    model_file_id: Mapped[int | None] = mapped_column(nullable=True)
    printer_id: Mapped[int | None] = mapped_column(nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )


class AppSetting(Base):
    """键值应用设置(MakerWorld Cookie、切片器路径等)。"""
    __tablename__ = "app_settings"

    key: Mapped[str] = mapped_column(String(64), primary_key=True)
    value: Mapped[dict] = mapped_column(JSON, default=dict)
