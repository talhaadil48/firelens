"""Phase 3: harvest all public PSI combustion investigations and selected NASA context.

Run `uv run python -m harvest.run`. Raw data remains local, not yet standardized.
"""

import argparse
import concurrent.futures
import json
import re
import time
from dataclasses import asdict
from datetime import UTC, datetime
from pathlib import Path

import httpx

from harvest.client import SourceClient
from harvest.context import capture, context_sources, html_text
from harvest.policy import (
    DOCUMENT_LIMIT,
    TABLE_LIMIT,
    accession_from,
    select_files,
    validate_document,
)
from harvest.spike import BASE_URL, csv_summary
from harvest.storage import Cache, HarvestError, TooLarge, atomic_bytes, write_json

ROOT = Path(__file__).resolve().parents[1]


def get_catalogue(
    client: SourceClient, folder: Path, page_size: int = 100
) -> tuple[list[dict], dict]:
    hits, pages, total, offset = {}, [], None, 0
    while True:
        url = str(
            httpx.URL(
                BASE_URL + "/geode-py/ws/repo/search",
                params={
                    "source": "psi",
                    "type": "investigation",
                    "size": page_size,
                    "from": offset,
                },
            )
        )
        path = folder / f"page-{offset:05}.json"
        receipt = client.resource(url, path, validator=json.loads, json_resource=True)
        payload = json.loads(path.read_bytes())
        if not isinstance(payload, dict):
            raise HarvestError("Catalogue response must be a JSON object")
        page = payload.get("hits", {}).get("hits")
        if not isinstance(page, list):
            raise HarvestError("Catalogue response is missing hits.hits")
        found_total = payload.get("hits", {}).get("total")
        if isinstance(found_total, dict):
            found_total = found_total.get("value")
        if isinstance(found_total, int):
            total = found_total
        pages.append(
            {
                "source_url": url,
                "file": path.name,
                "receipt": asdict(receipt),
                "returned": len(page),
            }
        )
        for hit in page:
            source = hit.get("_source", {})
            key = source.get("Accession") or hit.get("_id")
            if key:
                hits[key] = hit
        offset += len(page)
        if not page or (total is not None and offset >= total) or len(page) < page_size:
            if total is not None and offset < total:
                raise HarvestError("Catalogue pagination ended before the advertised total")
            break
        if len(pages) > 100:
            raise HarvestError("Catalogue pagination exceeded the safety bound")
    if total is not None and len(hits) != total:
        raise HarvestError(
            "Catalogue pages did not contain the advertised number of unique records"
        )
    filtered = [
        h
        for h in hits.values()
        if h.get("_source", {}).get("Research Area") == "Combustion Science"
    ]
    filtered.sort(key=lambda h: int(accession_from(h).split("-")[1]))
    if not filtered:
        raise HarvestError("Catalogue has no Combustion Science investigations")
    write_json(folder / "combustion.json", filtered)
    return filtered, {
        "total_records": len(hits),
        "advertised_total": total,
        "combustion_count": len(filtered),
        "pages": pages,
    }


def investigate(hit: dict, folder: Path, client: SourceClient) -> dict:
    started = time.perf_counter()
    accession = accession_from(hit)
    destination = folder / accession
    destination.mkdir(parents=True, exist_ok=True)
    url = BASE_URL + "/geode-py/ws/repo/investigations/" + accession
    record = {
        "accession": accession,
        "source_url": url,
        "status": "failed",
        "files": [],
        "skipped": {},
        "notes": [],
    }
    try:
        path = destination / "manifest.json"
        receipt = client.resource(url, path, validator=json.loads, json_resource=True)
        manifest = json.loads(path.read_bytes())
        if not isinstance(manifest, dict):
            raise HarvestError("Manifest response must be a JSON object")
        if manifest.get("accession") != accession:
            raise HarvestError("Manifest accession differs from requested investigation")
        if manifest.get("restricted") or manifest.get("public") is False:
            raise HarvestError("Investigation is not publicly accessible")
        if manifest.get("researchArea") != "Combustion Science":
            raise HarvestError("Manifest is not labelled Combustion Science")
        version = str(manifest.get("version", "unknown"))
        selected, skipped = select_files(accession, manifest)
        record.update(
            title=manifest.get("title"),
            doi=manifest.get("doi"),
            version=version,
            license={
                "identifier": manifest.get("licenseIdentifier"),
                "name": manifest.get("licenseName"),
                "url": manifest.get("licenseLink"),
            },
            hardware=manifest.get("experimentHardware"),
            manifest=asdict(receipt),
            skipped=skipped,
            listed_files=len(manifest.get("added") or []),
            experimental_table_entries=len(manifest.get("experimentalTable") or []),
        )
        if not manifest.get("experimentalTable"):
            record["notes"].append("No experimental table listed; metadata/documents only.")
        write_json(
            destination / "inventory.json",
            {
                **record,
                "status": "manifest_captured",
                "selected_files": selected,
            },
        )
        for item in selected:
            source = item["file"]
            entry = {
                "source_file": source.get("file_name"),
                "category": item["category"],
                "role": item["role"],
                "status": "failed",
                "file_version": source.get("version"),
            }
            t0 = time.perf_counter()
            try:
                if item.get("policy_error"):
                    raise HarvestError(item["policy_error"])
                if item["role"] == "table":
                    target = destination / item["local_name"]
                    validator = csv_summary
                else:
                    category_folder = item["category"].replace(" ", "_")
                    target = destination / "documents" / category_folder / item["local_name"]

                    def validator(b, name=source["file_name"]):
                        return validate_document(b, name)

                receipt = client.psi_file(
                    accession,
                    source,
                    target,
                    study_version=version,
                    limit=TABLE_LIMIT if item["role"] == "table" else DOCUMENT_LIMIT,
                    validator=validator,
                )
                entry.update(
                    status="success",
                    path=target.relative_to(folder).as_posix(),
                    receipt=asdict(receipt),
                )
                if item["role"] == "table":
                    entry["csv"] = csv_summary(target.read_bytes())
            except TooLarge as exc:
                if item["role"] == "document":
                    entry.update(status="skipped", reason=str(exc))
                else:
                    entry["error"] = str(exc)
            except (HarvestError, UnicodeError, ValueError, OSError) as exc:
                entry["error"] = safe_error(exc)
            entry["seconds"] = round(time.perf_counter() - t0, 3)
            record["files"].append(entry)
        record["status"] = (
            "success" if all(f["status"] != "failed" for f in record["files"]) else "partial"
        )
    except (HarvestError, ValueError, OSError) as exc:
        record["error"] = safe_error(exc)
    record["seconds"] = round(time.perf_counter() - started, 3)
    write_json(destination / "harvest.json", record)
    print(
        f"{accession}: {record['status']} — "
        f"{sum(f['status'] == 'success' for f in record['files'])} files",
        flush=True,
    )
    return record


def safe_error(exc: Exception) -> str:
    if isinstance(exc, HarvestError):
        return str(exc)
    # Decoder/filesystem/JSON errors can embed source data or OS paths: keep diagnostics bounded.
    return type(exc).__name__ + "; inspect the retained public source for details"


def markdown(report: dict) -> str:
    counts = report["counts"]
    lines = [
        "# Phase 3 harvest log",
        "",
        f"Run: `{report['run_id']}`",
        f"Started (UTC): {report['started_at']}",
        f"Status: **{report['status']}**",
        "",
        f"Raw folder: `{report['raw_folder']}`",
        "",
        f"- Combustion investigations: {counts['investigations']}",
        f"- Successful manifests: {counts['manifests']}",
        f"- Experimental CSVs saved: {counts['tables']}",
        f"- Supporting documents saved: {counts['documents']}",
        f"- Context sources captured: {counts['context_sources']}",
        f"- File downloads restored from verified cache: {counts['cache_hits']}",
        f"- Downloaded bytes (saved files): {counts['bytes']:,}",
        f"- Failures: {counts['failures']}",
        f"- Elapsed seconds: {report['seconds']}",
        "",
        (
            "CSV row counts include possible unit/description/blank rows "
            "and are not validated test counts."
        ),
        "Data is not yet standardized. Bulk Raw Data was not downloaded.",
        "",
        "## Investigation inventory",
        "",
        "| Investigation | Version | DOI | CSVs | Documents | Status |",
        "| --- | --- | --- | --- | --- | --- |",
    ]
    for row in report["investigations"]:
        files = row["files"]
        tables = sum(f["role"] == "table" and f["status"] == "success" for f in files)
        docs = sum(f["role"] == "document" and f["status"] == "success" for f in files)
        lines.append(
            f"| {row['accession']} | {row.get('version', '—')} | "
            f"{row.get('doi') or 'not supplied'} | {tables} | {docs} | {row['status']} |"
        )
    lines += ["", "## Context sources", ""]
    for item in report["context"]:
        lines.append(f"- {item['id']}: {item['status']} — {item['url']}")
    lines += ["", "## Failures and caveats", ""]
    issues = [report["fatal_error"]] if report.get("fatal_error") else []
    for row in report["investigations"]:
        if row.get("error"):
            issues.append(f"{row['accession']}: {row['error']}")
        for item in row["files"]:
            if item["status"] == "failed":
                issues.append(f"{row['accession']} / {item['source_file']}: {item['error']}")
        issues += [f"{row['accession']}: {note}" for note in row["notes"]]
    for item in report["context"]:
        if item.get("used_fallback"):
            issues.append(
                f"{item['id']}: requested {item['requested_url']} unavailable; "
                f"fallback captured at {item['url']}"
            )
        if item.get("error"):
            issues.append(f"{item['id']}: {item['error']}")
    if report.get("challenge", {}).get("error"):
        issues.append(
            "Official challenge resource page could not be captured: "
            + report["challenge"]["error"]
        )
    issues.append(
        "Context URLs are configured primary NASA references, "
        "not a verified complete official resource list."
    )
    issues.append(
        "Software/data collection success does not establish scientific validity or mission safety."
    )
    lines += ["- " + issue.replace("\n", " ") for issue in issues]
    return "\n".join(lines) + "\n"


def harvest(
    output: Path,
    run_id: str,
    sources_file: Path,
    *,
    workers: int = 3,
    offline: bool = False,
    refresh: bool = False,
    publish: Path | None = None,
    transport: httpx.BaseTransport | None = None,
) -> dict:
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{0,60}", run_id):
        raise HarvestError("Run ID must be a short safe folder name")
    if workers not in (3, 4):
        raise HarvestError("Harvest concurrency must be 3 or 4 workers")
    started = time.perf_counter()
    folder = output / run_id
    previous_report = folder / "report.json"
    if previous_report.exists():
        previous = json.loads(previous_report.read_text())
        if previous.get("status") == "complete":
            raise HarvestError("Completed raw runs are immutable; choose a new run ID")
    folder.mkdir(parents=True, exist_ok=True)
    client = SourceClient(
        Cache(output / "_cache"), offline=offline, refresh=refresh, transport=transport
    )
    report = {
        "run_id": run_id,
        "started_at": datetime.now(UTC).isoformat(),
        "raw_folder": str(folder),
        "status": "failed",
        "investigations": [],
        "context": [],
        "workers": workers,
        "offline": offline,
    }
    config = context_sources(sources_file)
    try:
        hits, catalogue = get_catalogue(client, folder / "catalogue")
        report["catalogue"] = catalogue
        print(
            f"Catalogue: {catalogue['total_records']} PSI investigations; "
            f"{len(hits)} Combustion Science",
            flush=True,
        )
        with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as pool:
            futures = [pool.submit(investigate, hit, folder, client) for hit in hits]
            for future in concurrent.futures.as_completed(futures):
                report["investigations"].append(future.result())
        report["investigations"].sort(key=lambda i: int(i["accession"].split("-")[1]))
        with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as pool:
            future_sources = {
                pool.submit(capture, source, folder / "context", client): source
                for source in config["sources"]
            }
            for future, source in future_sources.items():
                try:
                    item = future.result()
                except (HarvestError, ValueError, OSError) as exc:
                    item = {
                        "id": source["id"],
                        "url": source["url"],
                        "status": "failed",
                        "error": safe_error(exc),
                    }
                report["context"].append(item)
                print(f"Context {source['id']}: {item['status']}", flush=True)
        # Optional discovery: failure must be reported, but does not erase six captured NASA topics.
        challenge_url = config.get("challenge_url")
        if challenge_url:
            report["challenge"] = {"url": challenge_url}
            try:
                receipt = client.resource(
                    challenge_url,
                    folder / "context/challenge.html",
                    validator=html_text,
                    json_resource=True,
                )
                title, text = html_text((folder / "context/challenge.html").read_bytes())
                atomic_bytes(
                    folder / "context/challenge.txt",
                    f"Title: {title}\nSource URL: {challenge_url}\n\n{text}".encode(),
                )
                report["challenge"].update(status="success", receipt=asdict(receipt))
            except (HarvestError, ValueError, OSError) as exc:
                report["challenge"].update(status="unavailable", error=safe_error(exc))
    except (HarvestError, ValueError, OSError) as exc:
        report["fatal_error"] = safe_error(exc)
    finally:
        client.close()
    entries = [f for row in report["investigations"] for f in row["files"]]
    good = [f for f in entries if f["status"] == "success"]
    failures = (
        sum(row["status"] == "failed" for row in report["investigations"])
        + sum(f["status"] == "failed" for f in entries)
        + sum(c["status"] == "failed" for c in report["context"])
        + int("fatal_error" in report)
    )
    report["counts"] = {
        "investigations": report.get("catalogue", {}).get("combustion_count", 0),
        "manifests": sum("manifest" in row for row in report["investigations"]),
        "tables": sum(f["role"] == "table" for f in good),
        "documents": sum(f["role"] == "document" for f in good),
        "context_sources": sum(c["status"] == "success" for c in report["context"]),
        "failures": failures,
        "bytes": sum(f["receipt"]["bytes"] for f in good),
        "cache_hits": sum(f["receipt"]["cached"] for f in good),
    }
    if failures == 0 and report["counts"]["investigations"] > 0:
        report["status"] = "complete"
    elif report["investigations"]:
        report["status"] = "partial"
    report["seconds"] = round(time.perf_counter() - started, 3)
    write_json(folder / "report.json", report)
    atomic_bytes(folder / "HARVEST_LOG.md", markdown(report).encode())
    if report["status"] == "complete":
        write_json(
            output / "latest-harvest.json",
            {"run_id": run_id, "folder": run_id, "report": f"{run_id}/report.json"},
        )
    if publish is not None:
        write_json(publish / "report.json", report)
        atomic_bytes(publish / "HARVEST_LOG.md", markdown(report).encode())
    print(f"Harvest {report['status']}: {json.dumps(report['counts'])}", flush=True)
    print(f"Log: {folder / 'HARVEST_LOG.md'}", flush=True)
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=ROOT / "raw")
    parser.add_argument("--run-id", default=datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ"))
    parser.add_argument("--workers", type=int, choices=[3, 4], default=3)
    parser.add_argument("--sources", type=Path, default=ROOT / "config/context_sources.yaml")
    parser.add_argument("--offline", action="store_true", help="Use verified cache only")
    parser.add_argument(
        "--refresh", action="store_true", help="Refresh catalogue/manifests/context"
    )
    parser.add_argument("--publish-report", type=Path)
    args = parser.parse_args()
    if args.offline and args.refresh:
        parser.error("--offline and --refresh are mutually exclusive")
    try:
        report = harvest(
            args.output,
            args.run_id,
            args.sources,
            workers=args.workers,
            offline=args.offline,
            refresh=args.refresh,
            publish=args.publish_report,
        )
    except (HarvestError, OSError) as exc:
        parser.exit(1, safe_error(exc) + "\n")
    if report["status"] != "complete":
        parser.exit(
            1, "Harvest has recorded failures; inspect HARVEST_LOG.md and rerun to resume.\n"
        )


if __name__ == "__main__":
    main()
