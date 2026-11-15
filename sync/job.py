"""Phase 12 sync: rebuild the snapshot when PSI changes and publish it for this code's format.

Safety rules, in order of importance:

1. Only ``formats/<format id>/…`` pointers and new ``<snapshot_id>/…`` folders are written.
   The legacy root ``latest.json`` and older snapshots are never touched or deleted, so a run
   can't change what an API built for another format serves.
2. A snapshot is published only after it passes ``scripts.check_snapshot`` and is not
   noticeably smaller than the one already published (a partial PSI outage must not shrink
   the data). ``--force`` skips the size guard, never the validation.
3. The pointer is written last, after every file it names is in place.
"""

from __future__ import annotations

import hashlib
import json
import shutil
from collections.abc import Callable
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path

import httpx

from api.config import ROOT
from api.models import SnapshotPointer
from api.snapshot_format import SNAPSHOT_FORMAT_ID, pointer_blob_path
from scripts.check_snapshot import check_dir
from sync.blob import BlobReader, BlobWriter

POINTER_CACHE_CONTROL = "no-cache"

CatalogueFn = Callable[[Path], list[dict]]
BuildFn = Callable[[Path, str], Path]


@dataclass
class SyncSettings:
    work_dir: Path = Path("/tmp/firelens-sync")
    maps_dir: Path = ROOT / "harvest/maps"
    sources_file: Path = ROOT / "config/context_sources.yaml"
    force: bool = False
    dry_run: bool = False
    refresh_after_days: int = 7
    min_test_ratio: float = 0.9


@dataclass
class SyncResult:
    status: str  # published | no_change | refused | dry_run
    format_id: str = SNAPSHOT_FORMAT_ID
    reasons: list[str] = field(default_factory=list)
    published_snapshot_id: str | None = None
    built_snapshot_id: str | None = None
    detail: str | None = None
    check: dict | None = None

    @property
    def ok(self) -> bool:
        return self.status in {"published", "no_change", "dry_run"}

    def to_json(self) -> str:
        return json.dumps(asdict(self) | {"ok": self.ok}, sort_keys=True)


def state_blob_path(format_id: str = SNAPSHOT_FORMAT_ID) -> str:
    return f"formats/{format_id}/sync-state.json"


def catalogue_fingerprint(hits: list[dict]) -> dict[str, str]:
    """One short hash per Combustion Science catalogue record."""
    fingerprint: dict[str, str] = {}
    for hit in hits:
        source = hit.get("_source", {})
        accession = str(source.get("Accession") or hit.get("_id") or "")
        if not accession:
            continue
        canonical = json.dumps(source, sort_keys=True, separators=(",", ":"), default=str)
        fingerprint[accession] = hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:16]
    return dict(sorted(fingerprint.items()))


def default_catalogue(transport: httpx.BaseTransport | None = None) -> CatalogueFn:
    def fetch(work_dir: Path) -> list[dict]:
        from harvest.client import SourceClient
        from harvest.run import get_catalogue
        from harvest.storage import Cache

        client = SourceClient(Cache(work_dir / "probe-cache"), refresh=True, transport=transport)
        try:
            hits, _ = get_catalogue(client, work_dir / "probe" / "catalogue")
        finally:
            client.close()
        return hits

    return fetch


def default_build(settings: SyncSettings, transport: httpx.BaseTransport | None = None) -> BuildFn:
    """Full harvest (no Raw Data folders) followed by the normal pipeline."""

    def build(work_dir: Path, snapshot_id: str) -> Path:
        from harvest.pipeline import run_pipeline
        from harvest.run import harvest

        raw_root = work_dir / "raw"
        report = harvest(raw_root, snapshot_id, settings.sources_file, transport=transport)
        if report.get("status") == "failed":
            raise RuntimeError(f"Harvest failed: {report.get('fatal_error', 'see report.json')}")
        snapshots_dir = work_dir / "snapshots"
        run_pipeline(
            stage="all",
            raw_dir=raw_root / snapshot_id,
            maps_dir=settings.maps_dir,
            snapshots_dir=snapshots_dir,
            snapshot_id=snapshot_id,
        )
        return snapshots_dir

    return build


def _read_json(reader: BlobReader, path: str) -> dict | list | None:
    try:
        raw = reader.get(path)
        return json.loads(raw) if raw is not None else None
    except (httpx.HTTPError, ValueError):
        return None


def _read_pointer(reader: BlobReader, path: str) -> SnapshotPointer | None:
    try:
        raw = reader.get(path)
        return SnapshotPointer.model_validate_json(raw) if raw is not None else None
    except (httpx.HTTPError, ValueError):
        return None


def _versions(payload: dict | list | None) -> dict[str, str]:
    items = payload.get("items", []) if isinstance(payload, dict) else (payload or [])
    return {
        str(item.get("accession")): str(item.get("version"))
        for item in items
        if isinstance(item, dict)
    }


def _parse_time(value: object) -> datetime | None:
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None


def run_sync(
    settings: SyncSettings,
    *,
    reader: BlobReader,
    writer: BlobWriter | None,
    catalogue: CatalogueFn,
    build: BuildFn,
    now: Callable[[], datetime] = lambda: datetime.now(UTC),
) -> SyncResult:
    """Decide, build, validate and publish. Raises only on unexpected errors."""
    if writer is None and not settings.dry_run:
        return SyncResult(status="refused", detail="No Blob credentials; use --dry-run.")

    pointer_path = pointer_blob_path()
    published = _read_pointer(reader, pointer_path)
    state = _read_json(reader, state_blob_path())
    state = state if isinstance(state, dict) else {}

    settings.work_dir.mkdir(parents=True, exist_ok=True)
    fingerprint = catalogue_fingerprint(catalogue(settings.work_dir))
    if not fingerprint:
        return SyncResult(status="refused", detail="PSI catalogue returned no Combustion records.")

    reasons: list[str] = []
    if published is None:
        reasons.append(f"nothing published for format {SNAPSHOT_FORMAT_ID}")
    if settings.force:
        reasons.append("forced")
    if state.get("catalogue") != fingerprint:
        reasons.append("PSI catalogue changed")
    built_at = _parse_time(state.get("built_at"))
    if built_at is None or now() - built_at >= timedelta(days=settings.refresh_after_days):
        reasons.append(f"periodic refresh (every {settings.refresh_after_days} days)")
    current_id = published.snapshot_id if published else None
    if not reasons:
        return SyncResult(status="no_change", published_snapshot_id=current_id)

    snapshot_id = now().strftime("%Y%m%dT%H%M%SZ")
    snapshots_dir = build(settings.work_dir, snapshot_id)

    code, check = check_dir(snapshots_dir)
    result = SyncResult(
        status="refused",
        reasons=reasons,
        published_snapshot_id=current_id,
        built_snapshot_id=check.snapshot_id,
        check=asdict(check),
    )
    if code != 0 or not check.ok:
        result.detail = "Built snapshot failed validation; nothing published."
        return result

    pointer_bytes = (snapshots_dir / "latest.json").read_bytes()
    pointer = SnapshotPointer.model_validate_json(pointer_bytes)
    snap_dir = snapshots_dir / pointer.snapshot_id

    if published is not None and not settings.force:
        if pointer.investigation_count < published.investigation_count:
            result.detail = (
                f"Refused: {pointer.investigation_count} investigations, "
                f"{published.investigation_count} published."
            )
            return result
        if pointer.test_count < settings.min_test_ratio * published.test_count:
            result.detail = (
                f"Refused: {pointer.test_count} test rows, {published.test_count} published "
                f"(minimum {settings.min_test_ratio:.0%})."
            )
            return result

    new_state = {
        "format_id": SNAPSHOT_FORMAT_ID,
        "catalogue": fingerprint,
        "built_at": now().isoformat(),
        "snapshot_id": pointer.snapshot_id,
    }

    unchanged = (
        published is not None
        and not settings.force
        and "nothing published" not in " ".join(reasons)
        and (pointer.investigation_count, pointer.test_count, pointer.chunk_count)
        == (published.investigation_count, published.test_count, published.chunk_count)
        and _versions(_read_json(reader, f"{published.snapshot_id}/investigations.json"))
        == _versions(json.loads((snap_dir / "investigations.json").read_text(encoding="utf-8")))
    )

    if settings.dry_run:
        result.status = "dry_run"
        result.detail = f"Built and validated in {snap_dir}; nothing written to Blob."
        return result

    assert writer is not None
    if unchanged:
        new_state["snapshot_id"] = published.snapshot_id  # type: ignore[union-attr]
        writer.put(state_blob_path(), json.dumps(new_state, indent=2).encode("utf-8"))
        result.status = "no_change"
        result.detail = "Rebuilt snapshot matches the published one; pointer left as is."
        return result

    for name in pointer.files:
        writer.put(f"{pointer.snapshot_id}/{name}", (snap_dir / name).read_bytes())
    writer.put(pointer_path, pointer_bytes, cache_control=POINTER_CACHE_CONTROL)
    writer.put(state_blob_path(), json.dumps(new_state, indent=2).encode("utf-8"))
    result.status = "published"
    result.published_snapshot_id = pointer.snapshot_id
    result.detail = f"Published {pointer.snapshot_id} to {pointer_path}."
    return result


def clean_work_dir(path: Path) -> None:
    shutil.rmtree(path, ignore_errors=True)
