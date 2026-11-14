"""Validate canonical plan rows without discarding measurements or provenance."""

import pandas as pd
import pandera.pandas as pa
from pandera.typing import Series

from api.models import ExperimentalTest


class TestFrame(pa.DataFrameModel):
    test_id: Series[str] = pa.Field(str_length={"min_value": 1})
    accession: Series[str] = pa.Field(str_matches=r"^PSI-\d+$")
    investigation: Series[str] = pa.Field(nullable=True)
    test_date: Series[pd.Timestamp] = pa.Field(nullable=True)
    fuel: Series[str] = pa.Field(nullable=True)
    fuel_phase: Series[str] = pa.Field(isin=["solid", "liquid", "gas", "mixed", "unknown"])
    sample_geometry: Series[str] = pa.Field(nullable=True)
    sample_size_mm: Series[float] = pa.Field(nullable=True, gt=0)
    o2_fraction: Series[float] = pa.Field(nullable=True, ge=0, le=1)
    pressure_kpa: Series[float] = pa.Field(nullable=True, gt=0)
    diluent: Series[str] = pa.Field(nullable=True)
    flow_cm_s: Series[float] = pa.Field(nullable=True, ge=0)
    flow_direction: Series[str] = pa.Field(nullable=True)
    outcome: Series[str] = pa.Field(
        nullable=True, isin=["ignited", "extinguished", "cool_flame", "failed", "unknown"]
    )
    metrics: Series[object]
    source_url: Series[str] = pa.Field(str_matches=r"^https://")
    source_file: Series[str] = pa.Field(str_length={"min_value": 1})
    source_version: Series[str] = pa.Field(str_length={"min_value": 1})
    source_row: Series[int] = pa.Field(ge=1)
    doi: Series[str] = pa.Field(nullable=True)

    class Config:
        # Remaining Pydantic-validated geometry/evidence fields are preserved.
        strict = False
        coerce = True
        unique = ["accession", "test_id"]


def validate_tests(rows: list[ExperimentalTest]) -> pd.DataFrame:
    records = []
    for row in rows:
        record = row.model_dump(mode="json")
        record.update(
            source_url=str(row.provenance.source_url), source_version=row.provenance.source_version
        )
        records.append(record)
    # Explicit columns permit a truly empty validated table, without fake records.
    columns = list(dict.fromkeys([*TestFrame.to_schema().columns, *ExperimentalTest.model_fields]))
    frame = pd.DataFrame(records, columns=columns)
    return TestFrame.validate(frame, lazy=True)
