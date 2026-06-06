from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_name: str = "Fovea"
    app_version: str = "0.1.0"
    api_prefix: str = "/api/v1"
    database_url: str = "postgresql+asyncpg://fovea:fovea@postgres:5432/fovea"
    assets_path: str = "/data/fovea/assets"
    frontend_dist_path: str = "/app/frontend/dist"
    web_origin: str = "http://localhost:5173"
    rename_detection: str = "partial_hash"

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )


@lru_cache
def get_settings() -> Settings:
    return Settings()
