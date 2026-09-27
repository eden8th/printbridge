"""全局配置。所有配置可用环境变量覆盖(前缀 PB_),docker-compose 中注入。"""
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

BASE_DIR = Path(__file__).resolve().parents[2]  # server/


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="PB_", env_file=".env", extra="ignore")

    # sqlite 供开发机零依赖启动;docker-compose 注入 PostgreSQL 地址
    database_url: str = f"sqlite+aiosqlite:///{BASE_DIR / 'data' / 'printbridge.db'}"
    data_dir: Path = BASE_DIR / "data"          # 模型/G-code/日志 根目录
    profiles_dir: Path = BASE_DIR / "profiles"  # 内置切片参数包
    host: str = "0.0.0.0"
    port: int = 8000

    # 角色预留:server|worker 角色,worker 模式处理异步任务
    role: str = "server"
    relay_url: str = ""

    # 远程文件下载单文件上限(防滥用/防炸弹),默认 2GB
    max_download_bytes: int = 2 * 1024**3


settings = Settings()
settings.data_dir.mkdir(parents=True, exist_ok=True)
