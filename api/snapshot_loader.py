"""Compatibility re-export of api.snapshot (see docs/PARALLEL_PLAN.md)."""

from api.snapshot import (
    BlobFetcher,
    LoadedSnapshot,
    SnapshotLoader,
    row_from_duckdb_record,
    write_tests_parquet,
)

__all__ = [
    "BlobFetcher",
    "LoadedSnapshot",
    "SnapshotLoader",
    "row_from_duckdb_record",
    "write_tests_parquet",
]
