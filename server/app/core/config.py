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

    # 局域网发现:额外扫描的网段(逗号分隔 CIDR)。容器部署时容器内只能看到
    # Docker 网桥网段,需在 compose 中显式注入,如 PB_SCAN_CIDRS=192.168.8.0/24
    scan_cidrs: str = ""

    # 摄像头 go2rtc sidecar API(camera 容器,host 网络)
    camera_api: str = "http://host.docker.internal:1984"

    # 单次切片子进程超时(秒),防 Orca 卡死拖死整个队列
    slice_timeout: int = 900


settings = Settings()
settings.data_dir.mkdir(parents=True, exist_ok=True)
