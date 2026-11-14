"""API configuration and illustrative mission profiles."""

from pathlib import Path
from typing import Literal

import yaml
from pydantic import AliasChoices, Field, ValidationInfo, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from api.models import ProfileConfig

ROOT = Path(__file__).resolve().parents[1]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="FIRELENS_",
        extra="ignore",
        populate_by_name=True,
    )
    mode: Literal["mock", "snapshot", "auto"] = Field(
        default="mock",
        validation_alias=AliasChoices("FIRELENS_MODE", "mode"),
    )
    cors_origins: list[str] = Field(
        default=["http://localhost:5173"],
        validation_alias=AliasChoices("FIRELENS_CORS_ORIGINS", "cors_origins"),
    )
    psi_base_url: str = Field(
        default="https://psi.nasa.gov",
        validation_alias=AliasChoices("PSI_BASE_URL", "FIRELENS_PSI_BASE_URL"),
    )
    snapshots_dir: Path = Field(
        default=ROOT / "snapshots",
        validation_alias=AliasChoices("FIRELENS_SNAPSHOTS_DIR", "SNAPSHOTS_DIR"),
    )
    snapshot_refresh_seconds: int = Field(
        default=900,
        ge=1,
        validation_alias=AliasChoices(
            "FIRELENS_SNAPSHOT_REFRESH_SECONDS", "SNAPSHOT_REFRESH_SECONDS"
        ),
    )
    catalogue_cache_seconds: int = Field(
        default=3600,
        ge=1,
        validation_alias=AliasChoices(
            "FIRELENS_CATALOGUE_CACHE_SECONDS", "CATALOGUE_CACHE_SECONDS"
        ),
    )
    chat_rate_limit_per_minute: int = Field(
        default=20,
        ge=1,
        validation_alias=AliasChoices("FIRELENS_CHAT_RATE_LIMIT", "CHAT_RATE_LIMIT_PER_MINUTE"),
    )
    enable_live_catalogue_check: bool = Field(
        default=False,
        validation_alias=AliasChoices(
            "FIRELENS_LIVE_CATALOGUE_CHECK", "ENABLE_LIVE_CATALOGUE_CHECK"
        ),
    )
    azure_openai_endpoint: str = Field(
        default="",
        validation_alias=AliasChoices("AZURE_OPENAI_ENDPOINT", "FIRELENS_AZURE_OPENAI_ENDPOINT"),
    )
    azure_openai_api_key: str = Field(
        default="",
        repr=False,
        validation_alias=AliasChoices(
            "AZURE_OPENAI_API_KEY", "FIRELENS_AZURE_OPENAI_API_KEY", "OPENAI_API_KEY"
        ),
    )
    azure_openai_api_version: str = Field(
        default="2024-10-21",
        validation_alias=AliasChoices(
            "AZURE_OPENAI_API_VERSION", "FIRELENS_AZURE_OPENAI_API_VERSION"
        ),
    )
    azure_openai_chat_deployment: str = Field(
        default="gpt-4o-mini",
        validation_alias=AliasChoices(
            "AZURE_OPENAI_CHAT_DEPLOYMENT", "FIRELENS_AZURE_OPENAI_CHAT_DEPLOYMENT"
        ),
    )
    azure_openai_embedding_deployment: str = Field(
        default="text-embedding-3-small",
        validation_alias=AliasChoices(
            "AZURE_OPENAI_EMBEDDING_DEPLOYMENT", "FIRELENS_AZURE_OPENAI_EMBEDDING_DEPLOYMENT"
        ),
    )
    azure_storage_account_url: str = Field(
        default="",
        validation_alias=AliasChoices(
            "AZURE_STORAGE_ACCOUNT_URL", "FIRELENS_AZURE_STORAGE_ACCOUNT_URL"
        ),
    )
    azure_storage_container: str = Field(
        default="snapshots",
        validation_alias=AliasChoices(
            "AZURE_STORAGE_CONTAINER", "FIRELENS_AZURE_STORAGE_CONTAINER"
        ),
    )

    @field_validator(
        "psi_base_url",
        "azure_openai_api_version",
        "azure_openai_chat_deployment",
        "azure_openai_embedding_deployment",
        "azure_storage_container",
        mode="before",
    )
    @classmethod
    def _fallback_empty_defaults(cls, value: object, info: ValidationInfo) -> object:
        if value == "" and info.field_name is not None:
            return cls.model_fields[info.field_name].default
        return value


def load_profiles() -> ProfileConfig:
    return ProfileConfig.model_validate(yaml.safe_load((ROOT / "config/profiles.yaml").read_text()))
