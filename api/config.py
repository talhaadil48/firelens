from pathlib import Path

import yaml
from pydantic_settings import BaseSettings, SettingsConfigDict

from api.models import ProfileConfig

ROOT = Path(__file__).resolve().parents[1]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="FIRELENS_", extra="ignore")
    mode: str = "mock"
    cors_origins: list[str] = ["http://localhost:5173"]


def load_profiles() -> ProfileConfig:
    return ProfileConfig.model_validate(yaml.safe_load((ROOT / "config/profiles.yaml").read_text()))
