"""Pydantic contract for Phase 4 CSV column-map YAML files under harvest/maps/."""

from typing import Literal

from pydantic import Field

from api.models import Accession, Model, ReviewStatus

OutcomeLabel = Literal["ignited", "extinguished", "cool_flame", "failed", "unknown"]


class ColumnMapping(Model):
    """Maps one source CSV column to a canonical ExperimentalTest field."""

    source_column: str = Field(min_length=1)
    unit: str | None = None
    multiplier: float | None = Field(default=None, gt=0, allow_inf_nan=False)
    offset: float = Field(default=0.0, allow_inf_nan=False)
    date_format: str | None = None
    split_delimiter: str | None = None
    range_policy: Literal["keep_null", "min_max_metadata", "study_level_only"] = "keep_null"


class MetricMapping(Model):
    """Maps one source CSV column to a named entry in ExperimentalTest.metrics."""

    source_column: str = Field(min_length=1)
    unit: str = Field(min_length=1, description="Use '1' for dimensionless values")
    multiplier: float | None = Field(default=None, gt=0, allow_inf_nan=False)


class ColumnMap(Model):
    """Schema for harvest/maps/PSI-<n>.yaml used in Phase 4 normalization."""

    schema_version: Literal[1] = 1
    accession: Accession
    source_file: str = Field(min_length=1)
    encoding: str = Field(default="utf-8", min_length=1)
    header_row: int = Field(default=1, ge=1, description="1-based physical CSV header row")
    skip_rows: list[int] = Field(default_factory=list)
    id_column: str | None = None
    study_level_only: bool = False
    columns: dict[str, ColumnMapping] = Field(default_factory=dict)
    metrics: dict[str, MetricMapping] = Field(default_factory=dict)
    outcome_map: dict[str, OutcomeLabel] = Field(default_factory=dict)
    review_status: ReviewStatus = ReviewStatus.UNREVIEWED
    notes: list[str] = Field(default_factory=list)
