from pathlib import Path
from typing import Literal

import yaml
from pydantic_settings import BaseSettings, SettingsConfigDict

from api.models import ProfileConfig

ROOT = Path(__file__).resolve().parents[1]


class Settings(BaseSettings):
    """All runtime configuration comes from FIRELENS_* environment variables (rule 6)."""

    model_config = SettingsConfigDict(env_prefix="FIRELENS_", extra="ignore")
    # mock = Phase 2 fixtures in snapshots/sample; snapshot = snapshots/latest.json
    mode: Literal["mock", "snapshot"] = "mock"
    snapshot_dir: Path = ROOT / "snapshots"
    cors_origins: list[str] = ["http://localhost:5173"]
    # Rows from column maps a person has not approved are excluded from rankings unless
    # this is set (local development only; responses then carry a warning).
    allow_unreviewed: bool = False
    pointer_check_seconds: int = 15 * 60
    # Hourly PSI catalogue check behind /meta: the only PSI call in the request path.
    psi_check: bool = True
    psi_check_seconds: int = 60 * 60
    log_level: str = "INFO"


def load_profiles() -> ProfileConfig:
    return ProfileConfig.model_validate(yaml.safe_load((ROOT / "config/profiles.yaml").read_text()))
