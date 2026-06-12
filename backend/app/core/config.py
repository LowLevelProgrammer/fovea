from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

ROOT_DIR = Path(__file__).resolve().parents[3]

class Settings(BaseSettings):
    app_name: str = "Fovea"
    app_version: str = "0.1.0"
    api_prefix: str = "/api/v1"
    database_url: str = ""
    assets_path: str = "/data/fovea/assets"
    frontend_dist_path: str = "/app/frontend/dist"
    web_origin: str = "http://localhost:5173"
    rename_detection: str = "partial_hash"
    filesystem_watcher_enabled: bool = True
    watch_debounce_seconds: float = 2.0

    model_config = SettingsConfigDict(
        env_file=ROOT_DIR / ".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )


@lru_cache
def get_settings() -> Settings:
    return Settings()
