"""Check that a snapshot can be served by this code, using the API's own loaders.

Two ways to run it:

    # a local build: snapshots/latest.json and the folder it points to
    python -m scripts.check_snapshot --dir snapshots

    # what is published for this code's format (public HTTPS, no credentials)
    python -m scripts.check_snapshot --blob https://<account>.blob.core.windows.net/snapshots

Exit codes: 0 usable, 1 invalid, 2 nothing published for this format yet, 3 Blob unreachable.
"""

from __future__ import annotations

import argparse
import json
import sys
import tempfile
from dataclasses import asdict, dataclass, field
from pathlib import Path

import duckdb
import httpx

from api.models import SnapshotPointer
from api.snapshot import (
    _load_chunks_file,
    _load_investigations_file,
    _parquet_sql_source,
    row_from_duckdb_record,
)
from api.snapshot_format import PARQUET_COLUMNS, SNAPSHOT_FORMAT_ID, pointer_blob_path

EXIT_OK, EXIT_INVALID, EXIT_MISSING, EXIT_UNREACHABLE = 0, 1, 2, 3
SAMPLE_ROWS = 200
RANKABLE_SQL = "record_kind = 'individual_test' AND evidence_type = 'measurement'"


@dataclass
class Report:
    format_id: str = SNAPSHOT_FORMAT_ID
    snapshot_id: str | None = None
    investigations: int = 0
    tests: int = 0
    rankable_tests: int = 0
    chunks: int = 0
    problems: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.problems


def _short(exc: Exception) -> str:
    text = str(exc).strip().splitlines()
    return f"{type(exc).__name__}: {text[0] if text else ''}"[:300]


def validate_snapshot(pointer_bytes: bytes, snap_dir: Path) -> Report:
    """Validate a pointer and the snapshot folder it describes. Never raises."""
    report = Report()
    try:
        pointer = SnapshotPointer.model_validate_json(pointer_bytes)
    except Exception as exc:
        report.problems.append(f"pointer: {_short(exc)}")
        return report
    report.snapshot_id = pointer.snapshot_id

    missing = [name for name in pointer.files if not (snap_dir / name).is_file()]
    if missing:
        report.problems.append(f"missing files: {', '.join(missing)}")

    try:
        report.investigations = len(_load_investigations_file(snap_dir / "investigations.json"))
        if report.investigations != pointer.investigation_count:
            report.problems.append(
                f"investigations: {report.investigations} in file, "
                f"{pointer.investigation_count} in pointer"
            )
    except Exception as exc:
        report.problems.append(f"investigations.json: {_short(exc)}")

    try:
        report.chunks = len(_load_chunks_file(snap_dir / "chunks.jsonl"))
        if report.chunks != pointer.chunk_count:
            report.problems.append(
                f"chunks: {report.chunks} in file, {pointer.chunk_count} in pointer"
            )
    except Exception as exc:
        report.problems.append(f"chunks.jsonl: {_short(exc)}")

    parquet = snap_dir / "tests.parquet"
    if parquet.is_file():
        _check_parquet(parquet, pointer, report)
    return report


def _check_parquet(parquet: Path, pointer: SnapshotPointer, report: Report) -> None:
    source = _parquet_sql_source(parquet)
    try:
        with duckdb.connect(":memory:") as conn:
            columns = {
                row[0] for row in conn.execute(f"DESCRIBE SELECT * FROM {source}").fetchall()
            }
            absent = [name for name, _ in PARQUET_COLUMNS if name not in columns]
            if absent:
                report.problems.append(f"tests.parquet lacks columns: {', '.join(absent)}")
                return
            row = conn.execute(f"SELECT COUNT(*) FROM {source}").fetchone()
            report.tests = int(row[0]) if row else 0
            row = conn.execute(f"SELECT COUNT(*) FROM {source} WHERE {RANKABLE_SQL}").fetchone()
            report.rankable_tests = int(row[0]) if row else 0
            cursor = conn.execute(f"SELECT * FROM {source} LIMIT {SAMPLE_ROWS}")
            names = [col[0] for col in cursor.description]
            for index, values in enumerate(cursor.fetchall(), start=1):
                try:
                    row_from_duckdb_record(dict(zip(names, values, strict=True)))
                except Exception as exc:
                    report.problems.append(f"tests.parquet row {index}: {_short(exc)}")
                    break
    except Exception as exc:
        report.problems.append(f"tests.parquet: {_short(exc)}")
        return
    if report.tests != pointer.test_count:
        report.problems.append(f"tests: {report.tests} in file, {pointer.test_count} in pointer")
    if report.tests and not report.rankable_tests:
        report.problems.append("tests.parquet has no individual measurement rows to rank")


def check_dir(snapshots_dir: Path) -> tuple[int, Report]:
    """Check ``<snapshots_dir>/latest.json`` and the folder it names."""
    pointer_file = snapshots_dir / "latest.json"
    if not pointer_file.is_file():
        report = Report(problems=[f"{pointer_file} not found"])
        return EXIT_MISSING, report
    pointer_bytes = pointer_file.read_bytes()
    try:
        snapshot_id = json.loads(pointer_bytes)["snapshot_id"]
    except Exception as exc:
        return EXIT_INVALID, Report(problems=[f"pointer: {_short(exc)}"])
    report = validate_snapshot(pointer_bytes, snapshots_dir / snapshot_id)
    return (EXIT_OK if report.ok else EXIT_INVALID), report


def check_blob(
    container_url: str,
    *,
    pointer_path: str | None = None,
    transport: httpx.BaseTransport | None = None,
) -> tuple[int, Report]:
    """Download the published pointer for this format and its files, then validate them."""
    base = container_url.rstrip("/")
    pointer_path = pointer_path or pointer_blob_path()
    with httpx.Client(timeout=60.0, follow_redirects=True, transport=transport) as client:
        response = client.get(f"{base}/{pointer_path}")
        if response.status_code == 404:
            return EXIT_MISSING, Report(problems=[f"no pointer at {pointer_path}"])
        response.raise_for_status()
        pointer_bytes = response.content
        try:
            pointer = SnapshotPointer.model_validate_json(pointer_bytes)
        except Exception as exc:
            return EXIT_INVALID, Report(problems=[f"pointer: {_short(exc)}"])
        with tempfile.TemporaryDirectory() as tmp:
            snap_dir = Path(tmp) / pointer.snapshot_id
            for name in pointer.files:
                file_response = client.get(f"{base}/{pointer.snapshot_id}/{name}")
                if file_response.status_code == 404:
                    continue  # reported as a missing file
                file_response.raise_for_status()
                target = snap_dir / name
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(file_response.content)
            report = validate_snapshot(pointer_bytes, snap_dir)
    return (EXIT_OK if report.ok else EXIT_INVALID), report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    where = parser.add_mutually_exclusive_group(required=True)
    where.add_argument("--dir", type=Path, help="local snapshots folder holding latest.json")
    where.add_argument(
        "--blob", help="public container URL, e.g. https://x.blob.core.windows.net/snapshots"
    )
    parser.add_argument(
        "--pointer",
        default=None,
        help="pointer path inside the container (default: this code's format pointer)",
    )
    args = parser.parse_args(argv)

    if args.dir is not None:
        code, report = check_dir(args.dir)
    else:
        try:
            code, report = check_blob(args.blob, pointer_path=args.pointer)
        except httpx.HTTPError as exc:
            code, report = EXIT_UNREACHABLE, Report(problems=[f"download failed: {_short(exc)}"])
    print(json.dumps(asdict(report) | {"ok": report.ok, "exit_code": code}, indent=2))
    return code


if __name__ == "__main__":
    sys.exit(main())
