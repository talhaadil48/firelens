"""Phase 12 incremental PSI sync worker: diff, harvest changes, normalize, snapshot, upload."""

from __future__ import annotations

import argparse
import base64
import hashlib
import hmac
import json
import os
import shutil
import tempfile
import time
from collections.abc import Callable
from datetime import UTC, date, datetime
from email.utils import formatdate
from pathlib import Path
from typing import Any
from urllib.parse import quote, urlsplit

import httpx

from api.config import ROOT, Settings
from api.models import InvestigationList, SnapshotPointer
from api.snapshot import _resolve_snapshot_dir
from harvest.client import SourceClient
from harvest.context import capture, context_sources
from harvest.normalize import load_column_maps
from harvest.pipeline import _default_raw_dir, run_pipeline
from harvest.run import get_catalogue, investigate, markdown
from harvest.storage import Cache, HarvestError, atomic_bytes, write_json

BlobUploader = Callable[[str, bytes, str], None]

_DATE_FORMATS = ("%Y-%m-%d", "%d-%b-%Y", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%dT%H:%M:%SZ")


def _extract_source(hit: dict[str, Any]) -> dict[str, Any]:
    source = hit.get("_source")
    return source if isinstance(source, dict) else hit


def _hit_accession(hit: dict[str, Any]) -> str:
    source = _extract_source(hit)
    acc = source.get("Accession") or source.get("accession") or hit.get("_id")
    if not acc:
        raise HarvestError("Catalogue hit is missing Accession")
    return str(acc)


def _first_present(mapping: dict[str, Any], *keys: str) -> Any:
    for key in keys:
        if key in mapping and mapping[key] not in (None, ""):
            return mapping[key]
    return None


def _normalize_date_value(value: Any) -> Any:
    """Normalize epoch seconds or date strings to ISO YYYY-MM-DD when unambiguous."""
    if value in (None, ""):
        return None
    if isinstance(value, int | float):
        # PSI stores Unix timestamps (sometimes in ms if > 1e12).
        ts = float(value) / 1000.0 if float(value) > 1e12 else float(value)
        return datetime.fromtimestamp(ts, tz=UTC).date().isoformat()
    text = str(value).strip()
    try:
        return datetime.fromtimestamp(float(text), tz=UTC).date().isoformat()
    except ValueError:
        pass
    for fmt in _DATE_FORMATS:
        try:
            return datetime.strptime(text[:20], fmt).date().isoformat()
        except ValueError:
            continue
    try:
        return date.fromisoformat(text[:10]).isoformat()
    except ValueError:
        return text


def load_baseline_state(
    snapshots_dir: Path,
    base_raw_dir: Path | None,
) -> tuple[SnapshotPointer | None, dict[str, dict[str, Any]]]:
    """Load active snapshot investigation versions and base-harvest catalogue/manifest metadata."""
    baseline: dict[str, dict[str, Any]] = {}
    pointer: SnapshotPointer | None = None

    pointer_path = snapshots_dir / "latest.json"
    if pointer_path.exists():
        pointer = SnapshotPointer.model_validate_json(pointer_path.read_text(encoding="utf-8"))
        snap_dir = _resolve_snapshot_dir(pointer, snapshots_dir)
        if snap_dir is not None and (snap_dir / "investigations.json").exists():
            raw = json.loads((snap_dir / "investigations.json").read_text(encoding="utf-8"))
            inv_list = InvestigationList.model_validate(raw)
            for inv in inv_list.items:
                baseline[inv.accession] = {
                    "in_snapshot": True,
                    "version": str(inv.version),
                    "catalogue_version": None,
                    "catalogue_release_date": None,
                    "catalogue_modified_date": None,
                    "manifest_release_date": None,
                    "manifest_modified_date": None,
                }

    if base_raw_dir is not None and base_raw_dir.exists():
        catalogue_file = base_raw_dir / "catalogue/combustion.json"
        if catalogue_file.exists():
            hits = json.loads(catalogue_file.read_text(encoding="utf-8"))
            for hit in hits:
                acc = _hit_accession(hit)
                source = _extract_source(hit)
                entry = baseline.setdefault(acc, {"in_snapshot": False})
                entry["catalogue_version"] = _first_present(source, "Version", "version")
                entry["catalogue_release_date"] = _normalize_date_value(
                    _first_present(
                        source,
                        "Public Release Date",
                        "Release Date",
                        "releaseDate",
                        "release_date",
                    )
                )
                entry["catalogue_modified_date"] = _normalize_date_value(
                    _first_present(source, "Modified Date", "modifiedDate", "modified_date")
                )

        for manifest_path in sorted(base_raw_dir.glob("PSI-*/manifest.json")):
            acc = manifest_path.parent.name
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            entry = baseline.setdefault(acc, {"in_snapshot": False})
            if not entry.get("version") and manifest.get("version") is not None:
                entry["version"] = str(manifest["version"])
            entry["manifest_release_date"] = _normalize_date_value(manifest.get("releaseDate"))
            entry["manifest_modified_date"] = _normalize_date_value(manifest.get("modifiedDate"))

    return pointer, baseline


def diff_catalogue(
    hits: list[dict[str, Any]],
    baseline: dict[str, dict[str, Any]],
    base_raw_dir: Path | None = None,
) -> dict[str, Any]:
    """Compare live Combustion Science hits against baseline versions and release dates."""
    added: list[str] = []
    updated: list[str] = []
    unchanged: list[str] = []
    reasons: dict[str, str] = {}

    for hit in hits:
        acc = _hit_accession(hit)
        source = _extract_source(hit)
        live_ver = _first_present(source, "Version", "version")
        live_rel = _normalize_date_value(
            _first_present(
                source, "Public Release Date", "Release Date", "releaseDate", "release_date"
            )
        )
        live_mod = _normalize_date_value(
            _first_present(source, "Modified Date", "modifiedDate", "modified_date")
        )

        entry = baseline.get(acc)
        if entry is None or not entry.get("in_snapshot"):
            added.append(acc)
            reasons[acc] = "new investigation not in active snapshot"
            continue

        change_notes: list[str] = []
        base_ver = entry.get("version") or entry.get("catalogue_version")
        if live_ver is not None and base_ver is not None and str(live_ver) != str(base_ver):
            change_notes.append(f"version changed ({base_ver} -> {live_ver})")

        base_rel = entry.get("catalogue_release_date") or entry.get("manifest_release_date")
        if live_rel is not None and base_rel is not None and live_rel != base_rel:
            change_notes.append(f"release date changed ({base_rel} -> {live_rel})")

        base_mod = entry.get("catalogue_modified_date") or entry.get("manifest_modified_date")
        if live_mod is not None and base_mod is not None and live_mod != base_mod:
            change_notes.append(f"modified date changed ({base_mod} -> {live_mod})")

        if (
            not change_notes
            and base_raw_dir is not None
            and not (base_raw_dir / acc / "manifest.json").exists()
        ):
            change_notes.append("local manifest missing from base raw directory")

        if change_notes:
            updated.append(acc)
            reasons[acc] = "; ".join(change_notes)
        else:
            unchanged.append(acc)

    return {
        "added": added,
        "updated": updated,
        "unchanged": unchanged,
        "reasons": reasons,
    }


def find_unmapped_tables(raw_dir: Path, maps_dir: Path) -> list[dict[str, str]]:
    """Return raw CSV tables that lack a YAML column map in maps_dir."""
    mapped = {(cmap.accession, cmap.source_file) for cmap in load_column_maps(maps_dir)}
    unmapped: list[dict[str, str]] = []
    for csv_path in sorted(raw_dir.glob("PSI-*/*.csv")):
        acc = csv_path.parent.name
        if (acc, csv_path.name) not in mapped:
            unmapped.append({"accession": acc, "source_file": csv_path.name})
    return unmapped


def _reuse_investigation_from_base(
    acc: str,
    base_raw_dir: Path,
    raw_dir: Path,
) -> dict[str, Any]:
    """Copy an unchanged investigation directory from base_raw_dir and return its harvest record."""
    src_dir = base_raw_dir / acc
    dst_dir = raw_dir / acc
    if dst_dir.exists():
        shutil.rmtree(dst_dir)
    shutil.copytree(src_dir, dst_dir)

    harvest_json = dst_dir / "harvest.json"
    if harvest_json.exists():
        record = json.loads(harvest_json.read_text(encoding="utf-8"))
        for file_entry in record.get("files", []):
            receipt = file_entry.get("receipt")
            if isinstance(receipt, dict) and file_entry.get("status") == "success":
                receipt["cached"] = True
        record["reused_from_base"] = True
        return record

    manifest = json.loads((dst_dir / "manifest.json").read_text(encoding="utf-8"))
    return {
        "accession": acc,
        "source_url": f"https://psi.nasa.gov/geode-py/ws/repo/investigations/{acc}",
        "status": "success",
        "title": manifest.get("title"),
        "doi": manifest.get("doi"),
        "version": str(manifest.get("version") or "unknown"),
        "manifest": {"reused_from_base": True},
        "files": [],
        "skipped": {},
        "notes": ["Reused unchanged investigation from previous raw harvest."],
        "reused_from_base": True,
        "seconds": 0.0,
    }


def _copy_context_from_base(
    base_raw_dir: Path,
    raw_dir: Path,
    config: dict[str, Any],
) -> list[dict[str, Any]] | None:
    """Copy existing context captures from base_raw_dir when every configured source is present."""
    src_ctx = base_raw_dir / "context"
    if not src_ctx.exists():
        return None
    records: list[dict[str, Any]] = []
    for source in config.get("sources", []):
        meta_path = src_ctx / f"{source['id']}.source.json"
        if not meta_path.exists():
            return None
        records.append(json.loads(meta_path.read_text(encoding="utf-8")))
    dst_ctx = raw_dir / "context"
    if dst_ctx.exists():
        shutil.rmtree(dst_ctx)
    shutil.copytree(src_ctx, dst_ctx)
    return records


def _fetch_managed_identity_token() -> str:
    """Request a Storage access token from Azure Container Apps / App Service Managed Identity."""
    endpoint = os.environ.get("IDENTITY_ENDPOINT") or os.environ.get("MSI_ENDPOINT") or ""
    header_secret = os.environ.get("IDENTITY_HEADER") or os.environ.get("MSI_SECRET") or ""
    if not endpoint or not header_secret:
        raise HarvestError("Azure Managed Identity environment variables are not configured")
    headers = {"X-IDENTITY-HEADER": header_secret, "Metadata": "true"}
    params = {"api-version": "2019-08-01", "resource": "https://storage.azure.com/"}
    with httpx.Client(timeout=15.0) as client:
        resp = client.get(endpoint, params=params, headers=headers)
        resp.raise_for_status()
        token = resp.json().get("access_token")
    if not token:
        raise HarvestError("Azure Managed Identity response missing access_token")
    return str(token)


def _shared_key_authorization(
    *,
    account: str,
    storage_key: str,
    method: str,
    blob_url: str,
    content_length: int,
    content_type: str,
    x_ms_date: str,
    x_ms_version: str,
) -> str:
    """Compute an Azure Storage SharedKey Authorization header using stdlib HMAC-SHA256."""
    parsed = urlsplit(blob_url)
    canonical_headers = [
        "x-ms-blob-type:BlockBlob",
        f"x-ms-date:{x_ms_date}",
        f"x-ms-version:{x_ms_version}",
    ]
    canonical_headers.sort()
    canonical_resource = f"/{account}{quote(parsed.path, safe='/')}"
    string_to_sign = "\n".join(
        [
            method.upper(),
            "",
            "",
            str(content_length),
            "",
            content_type,
            "",
            "",
            "",
            "",
            "",
            "",
            *canonical_headers,
            canonical_resource,
        ]
    )
    decoded_key = base64.b64decode(storage_key)
    sig = base64.b64encode(
        hmac.new(decoded_key, string_to_sign.encode("utf-8"), hashlib.sha256).digest()
    ).decode("ascii")
    return f"SharedKey {account}:{sig}"


def _content_type_for(blob_path: str) -> str:
    lower = blob_path.lower()
    if lower.endswith(".json") or lower.endswith(".jsonl"):
        return "application/json"
    if lower.endswith(".md"):
        return "text/markdown; charset=utf-8"
    return "application/octet-stream"


def upload_snapshot_to_blob(
    snapshots_dir: Path,
    pointer: SnapshotPointer,
    *,
    account_url: str = "",
    container: str = "snapshots",
    sas_token: str = "",
    storage_key: str = "",
    blob_uploader: BlobUploader | None = None,
    transport: httpx.BaseTransport | None = None,
) -> list[str]:
    """Upload snapshot bundle files first, then upload latest.json pointer last."""
    snap_dir = _resolve_snapshot_dir(pointer, snapshots_dir)
    if snap_dir is None:
        raise FileNotFoundError(f"Snapshot directory not found for {pointer.snapshot_id}")

    latest_bytes = (snapshots_dir / "latest.json").read_bytes()
    upload_plan: list[tuple[str, bytes, str, str | None]] = []
    for rel_name in pointer.files:
        file_path = snap_dir / rel_name
        if not file_path.exists():
            raise FileNotFoundError(f"Missing snapshot artifact for upload: {file_path}")
        blob_path = f"{pointer.snapshot_id}/{rel_name}"
        upload_plan.append((blob_path, file_path.read_bytes(), _content_type_for(rel_name), None))
    upload_plan.append(("latest.json", latest_bytes, "application/json", "no-cache"))

    uploaded: list[str] = []
    if blob_uploader is not None:
        for blob_path, data, content_type, _ in upload_plan:
            blob_uploader(blob_path, data, content_type)
            uploaded.append(blob_path)
        return uploaded

    acct_url = (account_url or os.environ.get("AZURE_STORAGE_ACCOUNT_URL", "")).strip().rstrip("/")
    cont = (container or os.environ.get("AZURE_STORAGE_CONTAINER", "snapshots")).strip().strip("/")
    sas = (sas_token or os.environ.get("AZURE_STORAGE_SAS_TOKEN", "")).strip().lstrip("?")
    key = (storage_key or os.environ.get("AZURE_STORAGE_KEY", "")).strip()
    if not acct_url:
        raise HarvestError("AZURE_STORAGE_ACCOUNT_URL is required for Azure Blob upload")

    bearer_token: str | None = None
    if not sas and not key:
        if os.environ.get("IDENTITY_ENDPOINT") or os.environ.get("MSI_ENDPOINT"):
            bearer_token = _fetch_managed_identity_token()
        else:
            raise HarvestError(
                "Azure Blob upload requires Managed Identity, "
                "AZURE_STORAGE_SAS_TOKEN, or AZURE_STORAGE_KEY"
            )

    hostname = urlsplit(acct_url).hostname or ""
    account_name = hostname.split(".")[0]
    if not account_name:
        raise HarvestError(f"Invalid AZURE_STORAGE_ACCOUNT_URL: {acct_url!r}")
    x_ms_version = "2021-12-02"
    with httpx.Client(timeout=60.0, transport=transport) as client:
        for blob_path, data, content_type, cache_control in upload_plan:
            target_url = f"{acct_url}/{cont}/{blob_path.lstrip('/')}"
            request_url = f"{target_url}?{sas}" if sas else target_url
            x_ms_date = formatdate(usegmt=True)
            headers: dict[str, str] = {
                "x-ms-blob-type": "BlockBlob",
                "x-ms-version": x_ms_version,
                "x-ms-date": x_ms_date,
                "Content-Type": content_type,
            }
            if cache_control:
                headers["Cache-Control"] = cache_control
            if bearer_token is not None:
                headers["Authorization"] = f"Bearer {bearer_token}"
            elif key:
                headers["Authorization"] = _shared_key_authorization(
                    account=account_name,
                    storage_key=key,
                    method="PUT",
                    blob_url=target_url,
                    content_length=len(data),
                    content_type=content_type,
                    x_ms_date=x_ms_date,
                    x_ms_version=x_ms_version,
                )
            resp = client.put(request_url, content=data, headers=headers)
            resp.raise_for_status()
            uploaded.append(blob_path)
    return uploaded


def _append_sync_notes(
    snap_dir: Path,
    *,
    diff: dict[str, Any],
    unmapped_tables: list[dict[str, str]],
    previous_snapshot_id: str | None,
) -> None:
    """Append Phase 12 sync diff and unmapped-table notes to SNAPSHOT.md."""
    snapshot_md = snap_dir / "SNAPSHOT.md"
    existing = snapshot_md.read_text(encoding="utf-8") if snapshot_md.exists() else ""
    added_csv = ", ".join(diff["added"]) or "none"
    updated_csv = ", ".join(diff["updated"]) or "none"
    lines = [
        "",
        "## Phase 12 Incremental Sync",
        f"- Previous snapshot: `{previous_snapshot_id or 'none'}`",
        f"- Added investigations ({len(diff['added'])}): {added_csv}",
        f"- Updated investigations ({len(diff['updated'])}): {updated_csv}",
        f"- Reused unchanged investigations: {len(diff['unchanged'])}",
        f"- Unmapped CSV tables retaining source cells: {len(unmapped_tables)}",
    ]
    for item in unmapped_tables:
        lines.append(
            f"  - Flagged unmapped table: `{item['accession']}/{item['source_file']}` "
            "(source cells retained; scalar mapping needed before numeric ranking/charts)"
        )
    snapshot_md.write_text(existing.rstrip() + "\n" + "\n".join(lines) + "\n", encoding="utf-8")


def run_sync(
    *,
    raw_root: Path | None = None,
    base_raw_dir: Path | None = None,
    maps_dir: Path | None = None,
    snapshots_dir: Path | None = None,
    sources_file: Path | None = None,
    run_id: str | None = None,
    snapshot_id: str | None = None,
    workers: int = 3,
    offline: bool = False,
    force: bool = False,
    reharvest_all: bool = False,
    live_embeddings: bool = False,
    upload_blob: bool = False,
    transport: httpx.BaseTransport | None = None,
    blob_uploader: BlobUploader | None = None,
) -> dict[str, Any]:
    """Execute Phase 12 sync: check PSI catalogue diff, harvest delta, normalize, snapshot."""
    settings = Settings()
    resolved_raw_root = raw_root or (ROOT / "raw")
    resolved_maps_dir = maps_dir or (ROOT / "harvest/maps")
    resolved_snapshots_dir = snapshots_dir or settings.snapshots_dir
    resolved_sources_file = sources_file or (ROOT / "config/context_sources.yaml")
    resolved_base_raw = base_raw_dir
    if resolved_base_raw is None:
        candidate = _default_raw_dir()
        if candidate.exists() and (candidate / "catalogue/combustion.json").exists():
            resolved_base_raw = candidate

    timestamp_id = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    effective_run_id = run_id or f"sync-{timestamp_id}"
    effective_snapshot_id = snapshot_id or effective_run_id

    started = time.perf_counter()
    pointer, baseline = load_baseline_state(resolved_snapshots_dir, resolved_base_raw)
    config = context_sources(resolved_sources_file)

    client = SourceClient(
        Cache(resolved_raw_root / "_cache"),
        offline=offline,
        refresh=not offline,
        transport=transport,
    )
    try:
        with tempfile.TemporaryDirectory() as tmpdir:
            staging_cat = Path(tmpdir) / "catalogue"
            staging_cat.mkdir(parents=True, exist_ok=True)
            hits, catalogue = get_catalogue(client, staging_cat)
            diff = diff_catalogue(hits, baseline, resolved_base_raw)

            if not diff["added"] and not diff["updated"] and not force and pointer is not None:
                return {
                    "status": "up_to_date",
                    "changed": False,
                    "snapshot_id": pointer.snapshot_id,
                    "previous_snapshot_id": pointer.snapshot_id,
                    "added": [],
                    "updated": [],
                    "unchanged": diff["unchanged"],
                    "reasons": {},
                    "unmapped_tables": [],
                    "seconds": round(time.perf_counter() - started, 3),
                }

            raw_dir = resolved_raw_root / effective_run_id
            raw_dir.mkdir(parents=True, exist_ok=True)
            cat_dest = raw_dir / "catalogue"
            if cat_dest.exists():
                shutil.rmtree(cat_dest)
            shutil.copytree(staging_cat, cat_dest)

        unchanged_set = set(diff["unchanged"])
        harvest_records: list[dict[str, Any]] = []
        for hit in hits:
            acc = _hit_accession(hit)
            if (
                acc in unchanged_set
                and not reharvest_all
                and resolved_base_raw is not None
                and (resolved_base_raw / acc / "manifest.json").exists()
            ):
                reused = _reuse_investigation_from_base(acc, resolved_base_raw, raw_dir)
                harvest_records.append(reused)
            else:
                harvest_records.append(investigate(hit, raw_dir, client))
        harvest_records.sort(key=lambda item: int(item["accession"].split("-")[1]))

        context_records = (
            _copy_context_from_base(resolved_base_raw, raw_dir, config)
            if (not reharvest_all and resolved_base_raw is not None)
            else None
        )
        if context_records is None:
            context_records = []
            for source in config.get("sources", []):
                try:
                    context_records.append(capture(source, raw_dir / "context", client))
                except (HarvestError, ValueError, OSError) as exc:
                    context_records.append(
                        {
                            "id": source["id"],
                            "url": source["url"],
                            "status": "failed",
                            "error": str(exc),
                        }
                    )
    finally:
        client.close()

    entries = [f for row in harvest_records for f in row.get("files", [])]
    good = [f for f in entries if f.get("status") == "success"]
    failures = (
        sum(row.get("status") == "failed" for row in harvest_records)
        + sum(f.get("status") == "failed" for f in entries)
        + sum(c.get("status") == "failed" for c in context_records)
    )
    report = {
        "run_id": effective_run_id,
        "started_at": datetime.now(UTC).isoformat(),
        "raw_folder": str(raw_dir),
        "status": "complete" if failures == 0 and harvest_records else "partial",
        "catalogue": catalogue,
        "investigations": harvest_records,
        "context": context_records,
        "workers": workers,
        "offline": offline,
        "sync_diff": diff,
        "counts": {
            "investigations": len(harvest_records),
            "manifests": sum("manifest" in row for row in harvest_records),
            "tables": sum(f.get("role") == "table" for f in good),
            "documents": sum(f.get("role") == "document" for f in good),
            "context_sources": sum(c.get("status") == "success" for c in context_records),
            "failures": failures,
            "bytes": sum(f.get("receipt", {}).get("bytes", 0) for f in good),
            "cache_hits": sum(bool(f.get("receipt", {}).get("cached")) for f in good),
        },
        "seconds": round(time.perf_counter() - started, 3),
    }
    write_json(raw_dir / "report.json", report)
    atomic_bytes(raw_dir / "HARVEST_LOG.md", markdown(report).encode("utf-8"))

    failed_studies = [row["accession"] for row in harvest_records if row.get("status") == "failed"]
    if failed_studies:
        raise HarvestError(
            "Incremental sync aborted because investigation harvest failed for: "
            + ", ".join(failed_studies)
        )

    if failures == 0:
        write_json(
            resolved_raw_root / "latest-harvest.json",
            {
                "run_id": effective_run_id,
                "folder": effective_run_id,
                "report": f"{effective_run_id}/report.json",
            },
        )

    unmapped_tables = find_unmapped_tables(raw_dir, resolved_maps_dir)
    pipeline_result = run_pipeline(
        stage="all",
        raw_dir=raw_dir,
        maps_dir=resolved_maps_dir,
        snapshots_dir=resolved_snapshots_dir,
        snapshot_id=effective_snapshot_id,
        live_embeddings=live_embeddings,
    )
    new_pointer = SnapshotPointer.model_validate(pipeline_result["pointer"])
    snap_dir = _resolve_snapshot_dir(new_pointer, resolved_snapshots_dir)
    assert snap_dir is not None
    _append_sync_notes(
        snap_dir,
        diff=diff,
        unmapped_tables=unmapped_tables,
        previous_snapshot_id=pointer.snapshot_id if pointer else None,
    )

    sync_report: dict[str, Any] = {
        "status": "synced",
        "changed": True,
        "snapshot_id": effective_snapshot_id,
        "previous_snapshot_id": pointer.snapshot_id if pointer else None,
        "run_id": effective_run_id,
        "added": diff["added"],
        "updated": diff["updated"],
        "unchanged": diff["unchanged"],
        "reasons": diff["reasons"],
        "unmapped_tables": unmapped_tables,
        "stats": pipeline_result["stats"],
        "pointer": pipeline_result["pointer"],
        "uploaded_blobs": [],
        "seconds": round(time.perf_counter() - started, 3),
    }
    write_json(snap_dir / "sync_report.json", sync_report)

    if upload_blob or blob_uploader is not None:
        sync_report["uploaded_blobs"] = upload_snapshot_to_blob(
            resolved_snapshots_dir,
            new_pointer,
            account_url=settings.azure_storage_account_url,
            container=settings.azure_storage_container,
            blob_uploader=blob_uploader,
        )
        write_json(snap_dir / "sync_report.json", sync_report)

    return sync_report


def main(argv: list[str] | None = None) -> int:
    """CLI entry point for `python -m sync`."""
    parser = argparse.ArgumentParser(description="FireLens Phase 12 incremental PSI sync worker")
    parser.add_argument("--raw-root", type=Path, default=None)
    parser.add_argument("--base-raw-dir", type=Path, default=None)
    parser.add_argument("--maps-dir", type=Path, default=None)
    parser.add_argument("--snapshots-dir", type=Path, default=None)
    parser.add_argument("--sources-file", type=Path, default=None)
    parser.add_argument("--run-id", default=None)
    parser.add_argument("--snapshot-id", default=None)
    parser.add_argument("--workers", type=int, choices=[3, 4], default=3)
    parser.add_argument("--offline", action="store_true", help="Use verified cache only")
    parser.add_argument(
        "--force", action="store_true", help="Rebuild snapshot even if catalogue is unchanged"
    )
    parser.add_argument(
        "--reharvest-all",
        action="store_true",
        help="Re-download all investigations instead of reusing unchanged base directories",
    )
    parser.add_argument("--live-embeddings", action="store_true")
    parser.add_argument("--upload", action="store_true", help="Upload new snapshot to Azure Blob")
    args = parser.parse_args(argv)

    result = run_sync(
        raw_root=args.raw_root,
        base_raw_dir=args.base_raw_dir,
        maps_dir=args.maps_dir,
        snapshots_dir=args.snapshots_dir,
        sources_file=args.sources_file,
        run_id=args.run_id,
        snapshot_id=args.snapshot_id,
        workers=args.workers,
        offline=args.offline,
        force=args.force,
        reharvest_all=args.reharvest_all,
        live_embeddings=args.live_embeddings,
        upload_blob=args.upload,
    )
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
