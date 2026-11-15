"""Sync job decisions and publishing, with fake Blob, catalogue and build (no NASA, no Azure)."""

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import httpx
import pytest

from api.snapshot_format import pointer_blob_path
from sync.blob import HttpBlobWriter
from sync.job import SyncSettings, catalogue_fingerprint, run_sync, state_blob_path
from tests.test_phase6_api import _build_synthetic_snapshot

NOW = datetime(2026, 11, 16, 22, 0, tzinfo=UTC)
HITS = [
    {"_source": {"Accession": "PSI-25", "Research Area": "Combustion Science", "Title": "BASS-II"}},
    {"_source": {"Accession": "PSI-69", "Research Area": "Combustion Science", "Title": "FLEX"}},
]


class FakeBlob:
    """Reader and writer over one dict; records write order."""

    def __init__(self, files: dict[str, bytes] | None = None):
        self.files = dict(files or {})
        self.writes: list[str] = []

    def get(self, path: str) -> bytes | None:
        return self.files.get(path)

    def put(self, path: str, data: bytes, *, cache_control: str | None = None) -> None:
        self.files[path] = data
        self.writes.append(path)


def _builder(calls: list[str], *, mutate=None):
    def build(work_dir: Path, snapshot_id: str) -> Path:
        calls.append(snapshot_id)
        snapshots = work_dir / "snapshots"
        _build_synthetic_snapshot(snapshots, snapshot_id=snapshot_id)
        if mutate is not None:
            mutate(snapshots, snapshot_id)
        return snapshots

    return build


def _published_blob(tmp_path: Path, *, built_at: datetime = NOW, hits=HITS) -> FakeBlob:
    root = tmp_path / "published"
    snap_dir = _build_synthetic_snapshot(root, snapshot_id="pub-1")
    files = {f"pub-1/{p.name}": p.read_bytes() for p in snap_dir.iterdir()}
    files[pointer_blob_path()] = (root / "latest.json").read_bytes()
    files["latest.json"] = b'{"legacy": true}'
    state = {"catalogue": catalogue_fingerprint(hits), "built_at": built_at.isoformat()}
    files[state_blob_path()] = json.dumps(state).encode()
    return FakeBlob(files)


def _run(tmp_path: Path, blob: FakeBlob, calls: list[str], *, hits=HITS, mutate=None, **opts):
    settings = SyncSettings(work_dir=tmp_path / "work", **opts)
    return run_sync(
        settings,
        reader=blob,
        writer=None if settings.dry_run else blob,
        catalogue=lambda _work: hits,
        build=_builder(calls, mutate=mutate),
        now=lambda: NOW,
    )


def test_nothing_changed_means_no_build_and_no_writes(tmp_path: Path):
    blob, calls = _published_blob(tmp_path), []
    result = _run(tmp_path, blob, calls)
    assert result.status == "no_change" and result.ok
    assert calls == [] and blob.writes == []


def test_first_run_for_a_format_publishes_files_then_pointer_then_state(tmp_path: Path):
    blob, calls = FakeBlob(), []
    result = _run(tmp_path, blob, calls)
    assert result.status == "published", result.detail
    sid = calls[0]
    pointer_at = blob.writes.index(pointer_blob_path())
    assert all(w.startswith(f"{sid}/") for w in blob.writes[:pointer_at])
    assert blob.writes[pointer_at + 1 :] == [state_blob_path()]
    assert json.loads(blob.files[pointer_blob_path()])["snapshot_id"] == sid


def test_the_legacy_pointer_and_old_snapshots_are_never_written(tmp_path: Path):
    blob, calls = _published_blob(tmp_path), []
    changed = [HITS[0], {"_source": {**HITS[1]["_source"], "Title": "FLEX v2"}}]
    result = _run(tmp_path, blob, calls, hits=changed, force=True)
    assert result.status == "published"
    assert "latest.json" not in blob.writes
    assert not any(w.startswith("pub-1/") for w in blob.writes)
    assert blob.files["latest.json"] == b'{"legacy": true}'


def test_a_changed_catalogue_triggers_a_rebuild(tmp_path: Path):
    blob, calls = _published_blob(tmp_path), []
    changed = HITS + [{"_source": {"Accession": "PSI-99", "Research Area": "Combustion Science"}}]
    result = _run(tmp_path, blob, calls, hits=changed)
    assert calls, "expected a build"
    assert "PSI catalogue changed" in result.reasons


def test_an_identical_rebuild_keeps_the_pointer(tmp_path: Path):
    blob, calls = _published_blob(tmp_path, built_at=NOW - timedelta(days=8)), []
    result = _run(tmp_path, blob, calls)
    assert calls and result.status == "no_change"
    assert blob.writes == [state_blob_path()]
    assert json.loads(blob.files[pointer_blob_path()])["snapshot_id"] == "pub-1"


def test_a_snapshot_that_fails_validation_is_never_published(tmp_path: Path):
    def break_pointer(snapshots: Path, _sid: str) -> None:
        pointer = json.loads((snapshots / "latest.json").read_text(encoding="utf-8"))
        pointer["review_status"] = "reviewed"
        (snapshots / "latest.json").write_text(json.dumps(pointer), encoding="utf-8")

    blob, calls = FakeBlob(), []
    result = _run(tmp_path, blob, calls, mutate=break_pointer)
    assert result.status == "refused" and not result.ok
    assert blob.writes == []


def test_a_shrinking_snapshot_is_refused_unless_forced(tmp_path: Path):
    blob = _published_blob(tmp_path, built_at=NOW - timedelta(days=30))
    published = json.loads(blob.files[pointer_blob_path()])
    published["test_count"] *= 2  # the published snapshot had twice the rows a rebuild finds
    blob.files[pointer_blob_path()] = json.dumps(published).encode()

    result = _run(tmp_path, blob, [])
    assert result.status == "refused"
    assert "test rows" in (result.detail or "")
    assert blob.writes == []

    forced = _run(tmp_path, blob, [], force=True)
    assert forced.status == "published"


def test_dry_run_builds_and_validates_but_writes_nothing(tmp_path: Path):
    blob, calls = FakeBlob(), []
    result = _run(tmp_path, blob, calls, dry_run=True)
    assert result.status == "dry_run" and result.ok
    assert result.check and result.check["problems"] == []
    assert blob.writes == []


def test_without_credentials_a_real_run_refuses(tmp_path: Path):
    settings = SyncSettings(work_dir=tmp_path / "work")
    result = run_sync(
        settings,
        reader=FakeBlob(),
        writer=None,
        catalogue=lambda _w: pytest.fail("must not reach PSI"),
        build=lambda _w, _s: pytest.fail("must not build"),
    )
    assert result.status == "refused"


def test_blob_writer_sends_block_blob_puts_with_bearer_token():
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(201)

    writer = HttpBlobWriter(
        "https://acct.blob.core.windows.net",
        "snapshots",
        "tok",
        transport=httpx.MockTransport(handler),
    )
    writer.put("formats/x/latest.json", b"{}", cache_control="no-cache")
    request = seen[0]
    assert request.method == "PUT"
    assert request.url.path == "/snapshots/formats/x/latest.json"
    assert request.headers["authorization"] == "Bearer tok"
    assert request.headers["x-ms-blob-type"] == "BlockBlob"
    assert request.headers["x-ms-blob-cache-control"] == "no-cache"
    assert request.headers["x-ms-blob-content-type"] == "application/json"
