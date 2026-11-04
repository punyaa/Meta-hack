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

    @property
    def demo_mode(self) -> bool:
        return self.signalforge_demo_mode or not self.model_api_key


@lru_cache
def get_settings() -> Settings:
    settings = Settings()
    settings.data_dir.mkdir(parents=True, exist_ok=True)
    return settings

