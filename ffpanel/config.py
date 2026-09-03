from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="FFPANEL_", env_file=".env", extra="ignore")

    host: str = "0.0.0.0"
    port: int = 8080
    config_dir: Path = Path("/config")
    cache_dir: Path = Path("/cache")
    local_roots: str = "/media"
    database_url: str | None = None
    rclone_config: Path = Path("/config/rclone/rclone.conf")
    ffmpeg_path: str = "ffmpeg"
    ffprobe_path: str = "ffprobe"
    rclone_path: str = "rclone"
    auth_enabled: bool = False
    auth_username: str | None = None
    auth_password: str | None = None
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR"] = "INFO"
    mock_media: bool = False
    scan_ttl_seconds: int = Field(default=900, ge=60, le=3600)
    progress_persist_seconds: float = Field(default=3.0, ge=1.0, le=10.0)
    stop_timeout_seconds: float = Field(default=8.0, ge=1.0, le=30.0)

    @model_validator(mode="after")
    def validate_auth(self) -> Settings:
        if self.auth_enabled and (not self.auth_username or not self.auth_password):
            raise ValueError("Basic Auth 已启用，但用户名或密码为空")
        return self

    @property
    def db_url(self) -> str:
        return self.database_url or f"sqlite:///{(self.config_dir / 'ffpanel.db').as_posix()}"

    @property
    def allowed_local_roots(self) -> tuple[Path, ...]:
        values = [item.strip() for item in self.local_roots.split(",") if item.strip()]
        return tuple(Path(item).resolve() for item in values)

    def ensure_directories(self) -> None:
        self.config_dir.mkdir(parents=True, exist_ok=True)
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        for root in self.allowed_local_roots:
            root.mkdir(parents=True, exist_ok=True)


@lru_cache
def get_settings() -> Settings:
    return Settings()

