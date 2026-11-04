from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")

    app_name: str = "SignalForge"
    model_api_key: str | None = None
    muse_model: str = "muse-spark-1.3"
    sam_model: str = "sam-3.1"
    signalforge_demo_mode: bool = False
    max_images: int = 15
    retention_hours: int = 24
    data_dir: Path = Path("data/runs")
    storage_backend: str = "local"
    job_backend: str = "memory"
    blob_read_write_token: str | None = None
    web_flow: str = "auto"
    postgres_url: str | None = None
    session_secret: str | None = None
    google_api_key: str | None = None

    @property
    def demo_mode(self) -> bool:
        return self.signalforge_demo_mode or not self.model_api_key

    @property
    def serverless_mode(self) -> bool:
        return self.storage_backend == "blob"

    @property
    def flow(self) -> str:
        if self.web_flow in ("v1", "v2"):
            return self.web_flow
        return "v2" if self.serverless_mode else "v1"

    @property
    def db_configured(self) -> bool:
        return bool(self.postgres_url)


@lru_cache
def get_settings() -> Settings:
    settings = Settings()
    settings.data_dir.mkdir(parents=True, exist_ok=True)
    return settings

