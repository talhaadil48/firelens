"""Snapshot format id: which published snapshots this code can read.

The id is a short hash of every schema the API reads from a snapshot. Change a model the
snapshot depends on and the id changes, so the new API looks for a pointer published in its
own format (``formats/<id>/latest.json``) instead of reading data it would reject. The sync
job publishes into the same path. Older and newer API images can therefore share one Blob
container without breaking each other.

Run ``python -m api.snapshot_format`` to print the id.
"""

from __future__ import annotations

import hashlib
import json

from api.models import ExperimentalTest, Investigation, SnapshotPointer, TextChunk

# Column order and types of tests.parquet. Part of the format: the API's SQL relies on them.
PARQUET_COLUMNS: tuple[tuple[str, str], ...] = (
    ("test_id", "VARCHAR"),
    ("record_kind", "VARCHAR"),
    ("source_cells", "VARCHAR"),
    ("accession", "VARCHAR"),
    ("investigation", "VARCHAR"),
    ("test_date", "VARCHAR"),
    ("campaign_id", "VARCHAR"),
    ("fuel", "VARCHAR"),
    ("fuel_phase", "VARCHAR"),
    ("sample_geometry", "VARCHAR"),
    ("sample_size_mm", "DOUBLE"),
    ("sample_dimensions_mm", "VARCHAR"),
    ("thickness_mm", "DOUBLE"),
    ("o2_fraction", "DOUBLE"),
    ("oxygen_basis", "VARCHAR"),
    ("pressure_kpa", "DOUBLE"),
    ("diluent", "VARCHAR"),
    ("diluent_fractions", "VARCHAR"),
    ("flow_cm_s", "DOUBLE"),
    ("flow_direction", "VARCHAR"),
    ("gravity", "VARCHAR"),
    ("gravity_level_g", "DOUBLE"),
    ("platform", "VARCHAR"),
    ("outcome", "VARCHAR"),
    ("metrics", "VARCHAR"),
    ("outcome_value", "DOUBLE"),
    ("outcome_unit", "VARCHAR"),
    ("baseline_test_id", "VARCHAR"),
    ("source_file", "VARCHAR"),
    ("source_row", "BIGINT"),
    ("doi", "VARCHAR"),
    ("evidence_type", "VARCHAR"),
    ("provenance", "VARCHAR"),
    ("notes", "VARCHAR"),
    ("source_url", "VARCHAR"),
    ("source_version", "VARCHAR"),
)

LEGACY_POINTER_PATH = "latest.json"


def compute_format_id() -> str:
    """Hash the snapshot-facing schemas and the parquet columns into a 12-character id."""
    payload = {
        "pointer": SnapshotPointer.model_json_schema(mode="validation"),
        "investigation": Investigation.model_json_schema(mode="validation"),
        "test": ExperimentalTest.model_json_schema(mode="validation"),
        "chunk": TextChunk.model_json_schema(mode="validation"),
        "parquet": [list(column) for column in PARQUET_COLUMNS],
    }
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:12]


SNAPSHOT_FORMAT_ID = compute_format_id()


def pointer_blob_path(format_id: str = SNAPSHOT_FORMAT_ID) -> str:
    """Blob path of the pointer for snapshots built in ``format_id``."""
    return f"formats/{format_id}/latest.json"


if __name__ == "__main__":
    print(SNAPSHOT_FORMAT_ID)
