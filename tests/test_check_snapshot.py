"""Snapshot checker: accepts what the API can serve, rejects what it would fall back on."""

import json
from pathlib import Path

import duckdb
import httpx

from api.snapshot_format import SNAPSHOT_FORMAT_ID, pointer_blob_path
from scripts.check_snapshot import (
    EXIT_INVALID,
    EXIT_MISSING,
    EXIT_OK,
    check_blob,
    check_dir,
    main,
)
from tests.test_phase6_api import _build_synthetic_snapshot

BLOB = "https://example.blob.core.windows.net/snapshots"


def _snapshot(tmp_path: Path, snapshot_id: str = "snap-1") -> Path:
    return _build_synthetic_snapshot(tmp_path, snapshot_id=snapshot_id)


def test_a_freshly_built_snapshot_passes(tmp_path: Path):
    _snapshot(tmp_path)
    code, report = check_dir(tmp_path)
    assert code == EXIT_OK, report.problems
    assert report.snapshot_id == "snap-1"
    assert report.format_id == SNAPSHOT_FORMAT_ID
    assert report.tests > 0 and report.rankable_tests > 0
    assert report.investigations > 0 and report.chunks > 0


def test_a_pointer_with_a_removed_field_is_rejected(tmp_path: Path):
    """The 15 Nov break: latest.json still carried review_status after it was removed."""
    _snapshot(tmp_path)
    pointer = json.loads((tmp_path / "latest.json").read_text(encoding="utf-8"))
    pointer["review_status"] = "reviewed"
    (tmp_path / "latest.json").write_text(json.dumps(pointer), encoding="utf-8")

    code, report = check_dir(tmp_path)
    assert code == EXIT_INVALID
    assert report.problems[0].startswith("pointer:")


def test_investigations_with_unknown_fields_are_rejected(tmp_path: Path):
    snap_dir = _snapshot(tmp_path)
    path = snap_dir / "investigations.json"
    raw = json.loads(path.read_text(encoding="utf-8"))
    items = raw["items"] if isinstance(raw, dict) else raw
    items[0]["review_status"] = "reviewed"
    path.write_text(json.dumps(raw), encoding="utf-8")

    code, report = check_dir(tmp_path)
    assert code == EXIT_INVALID
    assert any(p.startswith("investigations.json") for p in report.problems)


def test_parquet_missing_a_column_the_api_queries_is_rejected(tmp_path: Path):
    snap_dir = _snapshot(tmp_path)
    parquet = snap_dir / "tests.parquet"
    old = snap_dir / "old.parquet"
    parquet.rename(old)
    duckdb.sql(
        f"COPY (SELECT * EXCLUDE (record_kind) FROM read_parquet('{old.as_posix()}')) "
        f"TO '{parquet.as_posix()}' (FORMAT PARQUET)"
    )
    old.unlink()

    code, report = check_dir(tmp_path)
    assert code == EXIT_INVALID
    assert any("record_kind" in p for p in report.problems)


def test_missing_files_and_wrong_counts_are_reported(tmp_path: Path):
    snap_dir = _snapshot(tmp_path)
    (snap_dir / "chunks.jsonl").unlink()
    code, report = check_dir(tmp_path)
    assert code == EXIT_INVALID
    assert any("missing files: chunks.jsonl" in p for p in report.problems)
    assert any(p.startswith("chunks:") for p in report.problems)


def test_no_local_pointer_means_missing(tmp_path: Path):
    code, _ = check_dir(tmp_path)
    assert code == EXIT_MISSING


def _serve(files: dict[str, bytes]) -> httpx.MockTransport:
    def handler(request: httpx.Request) -> httpx.Response:
        prefix = "/snapshots/"
        key = request.url.path.removeprefix(prefix)
        if key in files:
            return httpx.Response(200, content=files[key])
        return httpx.Response(404)

    return httpx.MockTransport(handler)


def _published(tmp_path: Path) -> dict[str, bytes]:
    snap_dir = _snapshot(tmp_path, "pub-1")
    files = {f"pub-1/{p.name}": p.read_bytes() for p in snap_dir.iterdir()}
    files[pointer_blob_path()] = (tmp_path / "latest.json").read_bytes()
    return files


def test_blob_check_validates_the_pointer_for_this_format(tmp_path: Path):
    code, report = check_blob(BLOB, transport=_serve(_published(tmp_path)))
    assert code == EXIT_OK, report.problems
    assert report.snapshot_id == "pub-1"


def test_blob_check_reports_missing_when_this_format_was_never_published(tmp_path: Path):
    files = _published(tmp_path)
    legacy = files.pop(pointer_blob_path())
    files["latest.json"] = legacy  # only the legacy pointer exists
    code, _ = check_blob(BLOB, transport=_serve(files))
    assert code == EXIT_MISSING


def test_blob_check_rejects_a_published_snapshot_the_code_cannot_read(tmp_path: Path):
    files = _published(tmp_path)
    pointer = json.loads(files[pointer_blob_path()]) | {"review_status": "reviewed"}
    files[pointer_blob_path()] = json.dumps(pointer).encode("utf-8")
    code, _ = check_blob(BLOB, transport=_serve(files))
    assert code == EXIT_INVALID


def test_cli_prints_a_json_report(tmp_path: Path, capsys):
    _snapshot(tmp_path)
    assert main(["--dir", str(tmp_path)]) == EXIT_OK
    printed = json.loads(capsys.readouterr().out)
    assert printed["ok"] is True
    assert printed["format_id"] == SNAPSHOT_FORMAT_ID
