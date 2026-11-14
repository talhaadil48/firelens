"""Tabular invariants shared with the Pydantic row contract."""

import pandas as pd
import pandera.pandas as pa
from pandera.typing import Series

from api.models import ExperimentalTest


class TestFrame(pa.DataFrameModel):
    test_id: Series[str] = pa.Field(str_length={"min_value": 1})
    accession: Series[str] = pa.Field(str_matches=r"^PSI-\d+$")
    o2_fraction: Series[float] = pa.Field(nullable=True, ge=0, le=1)
    pressure_kpa: Series[float] = pa.Field(nullable=True, gt=0)
    flow_cm_s: Series[float] = pa.Field(nullable=True, ge=0)
    sample_size_mm: Series[float] = pa.Field(nullable=True, gt=0)
    source_url: Series[str] = pa.Field(str_matches=r"^https://")
    source_file: Series[str] = pa.Field(str_length={"min_value": 1})
    source_version: Series[str] = pa.Field(str_length={"min_value": 1})
    source_row: Series[int] = pa.Field(ge=1)

    class Config:
        strict = True
        coerce = True
        unique = ["accession", "test_id"]


def validate_tests(rows: list[ExperimentalTest]) -> pd.DataFrame:
    records = []
    for row in rows:
        record = row.model_dump(mode="json")
        provenance = record.pop("provenance")
        records.append(
            {
                **{
                    key: record[key]
                    for key in [
                        "test_id",
                        "accession",
                        "o2_fraction",
                        "pressure_kpa",
                        "flow_cm_s",
                        "sample_size_mm",
                    ]
                },
                **{
                    key: provenance[key]
                    for key in ["source_url", "source_file", "source_version", "source_row"]
                },
            }
        )
    frame = pd.DataFrame(records, columns=list(TestFrame.to_schema().columns))
    return TestFrame.validate(frame, lazy=True)
