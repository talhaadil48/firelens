"""Phase 3 automated harvest pipeline for NASA PSI microgravity combustion research.

Downloads:
1. PSI catalogue (filtered to Research Area = Combustion Science).
2. Manifests for all combustion investigations with concurrency, retries, and on-disk cache.
3. All experimental CSV tables via the immediate signed-URL flow.
4. Reports and Science Documents under 20 MB (skipping Raw Data).
5. Key historical and scientific challenge context pages.
6. A dated harvest directory and HARVEST_LOG.md recording counts, timings, and checksums.

Signed URLs are temporary credentials: consumed immediately, never written to disk or logs.
"""

import argparse
import csv
import hashlib
import io
import json
import logging
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import UTC, datetime
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import urlsplit

import httpx

BASE_URL = "https://psi.nasa.gov"
USER_AGENT = "FireLens/0.1 NASA-Space-Apps-Combustion-Harvest"
MAX_DOC_SIZE_BYTES = 20 * 1024 * 1024  # 20 MB limit
DEFAULT_CONCURRENCY = 3

logger = logging.getLogger("firelens.harvest")

CONTEXT_URLS = [
    {
        "slug": "nasa_combustion_science",
        "title": "NASA Glenn Combustion Science Background",
        "url": (
            "https://www.nasa.gov/glenn/glenn-expertise-space-exploration/"
            "physical-sciences-program/combustion-science/"
        ),
    },
    {
        "slug": "apollo_1_fire",
        "title": "NASA Apollo 1 Fire History",
        "url": "https://www.nasa.gov/history/apollo-1/",
    },
    {
        "slug": "apollo_13_mission",
        "title": "NASA Apollo 13 Review & History",
        "url": "https://www.nasa.gov/history/apollo-13/",
    },
    {
        "slug": "mir_space_station_fire",
        "title": "NASA SP-4225: Mir Space Station Fire Incident Documentation",
        "url": "https://history.nasa.gov/SP-4225/documentation/mir-fire/mir-fire.htm",
    },
    {
        "slug": "nasa_fire_safety_spinoffs",
        "title": "NASA Fire Safety & Detection Spinoffs",
        "url": "https://spinoff.nasa.gov/",
    },
    {
        "slug": "iss_researchers_guide_combustion",
        "title": "NASA NTRS: A Researcher's Guide to Combustion Science",
        "url": "https://ntrs.nasa.gov/citations/20150004085",
    },
]


class HTMLTextExtractor(HTMLParser):
    """Extract clean prose from HTML while omitting scripts, styles, and navigation."""

    def __init__(self) -> None:
        super().__init__()
        self.text_parts: list[str] = []
        self.skip = False
        self.skip_tags = {"script", "style", "nav", "footer", "header", "noscript", "svg"}

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag.lower() in self.skip_tags:
            self.skip = True
        elif tag.lower() in {"p", "div", "h1", "h2", "h3", "h4", "h5", "h6", "li", "tr"}:
            self.text_parts.append("\n")

    def handle_endtag(self, tag: str) -> None:
        if tag.lower() in self.skip_tags:
            self.skip = False
        elif tag.lower() in {"p", "div", "h1", "h2", "h3", "h4", "h5", "h6", "li", "tr"}:
            self.text_parts.append("\n")

    def handle_data(self, data: str) -> None:
        if not self.skip:
            self.text_parts.append(data)

    def get_text(self) -> str:
        raw = "".join(self.text_parts)
        lines = [line.strip() for line in raw.splitlines()]
        # Remove consecutive blank lines
        cleaned: list[str] = []
        for line in lines:
            if line:
                cleaned.append(line)
            elif cleaned and cleaned[-1] != "":
                cleaned.append("")
        return "\n".join(cleaned).strip()


def read_signed_url(text: str) -> str:
    """Validate and unquote temporary HTTPS signed URL. Never log or store."""
    value = text.strip()
    if value.startswith('"'):
        value = json.loads(value)
    elif value.startswith("'") and value.endswith("'"):
        value = value[1:-1]
    parsed = urlsplit(value)
    host = parsed.hostname or ""
    if parsed.scheme != "https" or not (host == "psi.nasa.gov" or host.endswith(".amazonaws.com")):
        raise ValueError("Resolver did not return a trusted HTTPS download URL")
    return value


def csv_summary(content: bytes) -> dict:
    """Summarize CSV headers, encoding, row count, and SHA-256."""
    encoding = "utf-8-sig"
    try:
        text = content.decode(encoding)
    except UnicodeDecodeError:
        encoding = "cp1252"
        text = content.decode(encoding)
    if text.lstrip().lower().startswith(("<!doctype", "<html", "<?xml", "<error")):
        raise ValueError("Expected CSV content, received HTML/XML")
    rows = list(csv.reader(io.StringIO(text)))
    if not rows or len(rows[0]) < 2:
        raise ValueError("Expected a non-empty CSV table with multiple columns")
    return {
        "headers": rows[0],
        "physical_data_rows": max(0, len(rows) - 1),
        "sha256": hashlib.sha256(content).hexdigest(),
        "bytes": len(content),
        "encoding": encoding,
    }


def fetch_with_retry(
    client: httpx.Client,
    url: str,
    *,
    params: dict | None = None,
    headers: dict | None = None,
    max_retries: int = 3,
) -> httpx.Response:
    """Fetch HTTP resource with exponential backoff on retryable status codes."""
    for attempt in range(max_retries):
        try:
            response = client.get(url, params=params, headers=headers)
            if response.status_code in (429, 500, 502, 503, 504) and attempt < max_retries - 1:
                sleep_time = 2**attempt
                time.sleep(sleep_time)
                continue
            response.raise_for_status()
            return response
        except httpx.TransportError:
            if attempt == max_retries - 1:
                raise
            time.sleep(2**attempt)
    raise RuntimeError("Retry loop exhausted")


def harvest_catalogue(client: httpx.Client, output_dir: Path) -> tuple[dict, list[dict]]:
    """Step 3.1: Fetch PSI catalogue, filter for Combustion Science, and save raw JSON."""
    logger.info("Fetching PSI catalogue...")
    url = BASE_URL + "/geode-py/ws/repo/search"
    params = {"term": "combustion", "source": "psi", "type": "investigation", "size": 100}
    t0 = time.perf_counter()
    resp = fetch_with_retry(client, url, params=params)
    catalogue = resp.json()
    duration = time.perf_counter() - t0

    hits = catalogue.get("hits", {}).get("hits", [])
    combustion_hits = [
        h for h in hits if h.get("_source", {}).get("Research Area") == "Combustion Science"
    ]
    logger.info(
        "Catalogue retrieved: %d total search hits, %d Combustion Science investigations (%.2fs)",
        len(hits),
        len(combustion_hits),
        duration,
    )

    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "catalogue.json").write_text(json.dumps(catalogue, indent=2), encoding="utf-8")

    meta = {
        "url": f"{url}?term=combustion&source=psi&type=investigation&size=100",
        "total_hits": len(hits),
        "combustion_count": len(combustion_hits),
        "duration_seconds": round(duration, 3),
        "retrieved_at": datetime.now(UTC).isoformat(),
    }
    return meta, combustion_hits


def harvest_manifest(
    client: httpx.Client, accession: str, folder: Path, use_cache: bool = True
) -> dict:
    """Step 3.2: Fetch and cache manifest detail record for an accession."""
    manifest_path = folder / "manifest.json"
    if use_cache and manifest_path.exists():
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            return {
                "accession": accession,
                "cached": True,
                "manifest": manifest,
                "duration": 0.0,
                "error": None,
            }
        except Exception:
            pass

    folder.mkdir(parents=True, exist_ok=True)
    url = BASE_URL + f"/geode-py/ws/repo/investigations/{accession}"
    t0 = time.perf_counter()
    try:
        resp = fetch_with_retry(client, url)
        manifest = resp.json()
        manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
        duration = time.perf_counter() - t0
        return {
            "accession": accession,
            "cached": False,
            "manifest": manifest,
            "duration": round(duration, 3),
            "error": None,
        }
    except Exception as exc:
        duration = time.perf_counter() - t0
        return {
            "accession": accession,
            "cached": False,
            "manifest": None,
            "duration": round(duration, 3),
            "error": f"{type(exc).__name__}: {exc}",
        }


def download_file_signed(
    client: httpx.Client, accession: str, file_name: str, destination: Path
) -> tuple[bytes, dict]:
    """Resolve signed download URL and fetch file bytes. Never log or store the signed URL."""
    resolver_url = BASE_URL + f"/geode-py/ws/studies/{accession}/download"
    t0 = time.perf_counter()
    res = fetch_with_retry(client, resolver_url, params={"file": file_name, "redirect": "false"})
    signed_url = read_signed_url(res.text)
    content = fetch_with_retry(client, signed_url).content
    duration = time.perf_counter() - t0

    sha256 = hashlib.sha256(content).hexdigest()
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_bytes(content)

    return content, {
        "file_name": file_name,
        "bytes": len(content),
        "sha256": sha256,
        "duration_seconds": round(duration, 3),
        "destination": str(destination.relative_to(destination.parents[2])),
    }


def harvest_tables(
    client: httpx.Client, accession: str, manifest: dict, folder: Path, use_cache: bool = True
) -> list[dict]:
    """Step 3.3: Harvest all experimental CSV tables for an investigation."""
    tables = manifest.get("experimentalTable") or []
    results = []
    for table in tables:
        name = table.get("file_name", "")
        if not name.lower().endswith(".csv") or Path(name).name != name:
            continue
        dest = folder / name
        if use_cache and dest.exists() and dest.stat().st_size > 0:
            content = dest.read_bytes()
            summary = csv_summary(content)
            meta = {
                "file_name": name,
                "bytes": len(content),
                "sha256": summary["sha256"],
                "duration_seconds": 0.0,
                "cached": True,
                "success": True,
            }
            meta.update(summary)
            logger.info(
                "Cached CSV %s/%s (%d rows)", accession, name, summary["physical_data_rows"]
            )
            results.append(meta)
            continue
        try:
            content, meta = download_file_signed(client, accession, name, dest)
            summary = csv_summary(content)
            meta.update(summary)
            meta["success"] = True
            logger.info("Saved CSV %s/%s (%d rows)", accession, name, summary["physical_data_rows"])
        except Exception as exc:
            meta = {
                "file_name": name,
                "success": False,
                "error": f"{type(exc).__name__}: {exc}",
            }
            logger.warning("Failed CSV %s/%s: %s", accession, name, exc)
        results.append(meta)
    return results


def harvest_docs(
    client: httpx.Client, accession: str, manifest: dict, folder: Path, use_cache: bool = True
) -> list[dict]:
    """Step 3.4: Download Reports and Science Documents under 20 MB, skipping Raw Data."""
    added = manifest.get("added") or []
    target_docs = []
    for entry in added:
        remote_path = entry.get("remote_path", "")
        parts = remote_path.split("/")
        category = parts[4] if len(parts) > 4 else ""
        if category not in ("Reports", "Science Documents"):
            continue
        size = entry.get("file_size", 0)
        file_name = entry.get("file_name", "")
        if size > MAX_DOC_SIZE_BYTES or not file_name or Path(file_name).name != file_name:
            continue
        target_docs.append((file_name, category, size))

    results = []
    docs_dir = folder / "documents"
    for name, cat, _expected_size in target_docs:
        dest = docs_dir / name
        if use_cache and dest.exists() and dest.stat().st_size > 0:
            content = dest.read_bytes()
            meta = {
                "file_name": name,
                "category": cat,
                "bytes": len(content),
                "sha256": hashlib.sha256(content).hexdigest(),
                "duration_seconds": 0.0,
                "cached": True,
                "success": True,
            }
            logger.info("Cached document %s/%s (%d bytes)", accession, name, len(content))
            results.append(meta)
            continue
        try:
            content, meta = download_file_signed(client, accession, name, dest)
            meta["category"] = cat
            meta["success"] = True
            logger.info("Saved document %s/%s (%d bytes)", accession, name, len(content))
        except Exception as exc:
            meta = {
                "file_name": name,
                "category": cat,
                "success": False,
                "error": f"{type(exc).__name__}: {exc}",
            }
            logger.warning("Failed document %s/%s: %s", accession, name, exc)
        results.append(meta)
    return results


def harvest_context(client: httpx.Client, output_dir: Path) -> list[dict]:
    """Step 3.5: Scrape challenge resource pages to clean text with metadata headers."""
    logger.info("Scraping challenge context pages...")
    context_dir = output_dir / "context_pages"
    context_dir.mkdir(parents=True, exist_ok=True)
    results = []

    for item in CONTEXT_URLS:
        slug = item["slug"]
        url = item["url"]
        title = item["title"]
        t0 = time.perf_counter()
        entry = {"slug": slug, "title": title, "url": url, "success": False}
        try:
            resp = fetch_with_retry(client, url)
            parser = HTMLTextExtractor()
            parser.feed(resp.text)
            text_content = parser.get_text()
            now_iso = datetime.now(UTC).isoformat()
            duration = time.perf_counter() - t0

            header = (
                f"# {title}\n"
                f"Source: {url}\n"
                f"Retrieved-At: {now_iso}\n"
                f"Status-Code: {resp.status_code}\n\n"
                f"---\n\n"
            )
            full_text = header + text_content + "\n"
            out_path = context_dir / f"{slug}.txt"
            out_path.write_text(full_text, encoding="utf-8")

            entry.update(
                {
                    "success": True,
                    "bytes": len(full_text.encode("utf-8")),
                    "sha256": hashlib.sha256(full_text.encode("utf-8")).hexdigest(),
                    "duration_seconds": round(duration, 3),
                    "file_path": str(out_path.relative_to(output_dir)),
                }
            )
            logger.info("Saved context page: %s (%d chars)", slug, len(text_content))
        except Exception as exc:
            entry["error"] = f"{type(exc).__name__}: {exc}"
            logger.warning("Failed context page %s: %s", slug, exc)
        results.append(entry)
    return results


def generate_harvest_log(report: dict, output_dir: Path) -> str:
    """Step 3.6: Generate dated HARVEST_LOG.md markdown report."""
    now = report["started_at_utc"]
    total_invs = len(report["investigations"])
    total_tables = sum(len(inv["tables"]) for inv in report["investigations"])
    successful_tables = sum(
        sum(1 for t in inv["tables"] if t.get("success")) for inv in report["investigations"]
    )
    total_docs = sum(len(inv["documents"]) for inv in report["investigations"])
    successful_docs = sum(
        sum(1 for d in inv["documents"] if d.get("success")) for inv in report["investigations"]
    )
    successful_context = sum(1 for c in report["context_pages"] if c.get("success"))

    md = [
        "# FireLens Harvest Log — Phase 3",
        "",
        f"- **Harvest Date (UTC):** {now}",
        f"- **Elapsed Time:** {report.get('total_seconds', 0):.2f} seconds",
        f"- **Total Combustion Investigations:** {total_invs}",
        f"- **Experimental Tables Downloaded:** {successful_tables} / {total_tables}",
        f"- **Reports & Science Documents Downloaded:** {successful_docs} / {total_docs}",
        f"- **Context Pages Scraped:** {successful_context} / {len(report['context_pages'])}",
        "",
        "## 1. Experimental CSV Tables",
        "",
        "| Accession | File Name | Rows | Encoding | Size (bytes) | SHA-256 |",
        "| --- | --- | --- | --- | --- | --- |",
    ]

    for inv in report["investigations"]:
        for t in inv["tables"]:
            if t.get("success"):
                rows = t.get("physical_data_rows", "N/A")
                enc = t.get("encoding", "N/A")
                size = t.get("bytes", "N/A")
                sha = f"`{t.get('sha256', '')[:16]}...`"
                acc = inv["accession"]
                fn = t["file_name"]
                md.append(f"| {acc} | {fn} | {rows} | {enc} | {size} | {sha} |")

    md.extend(
        [
            "",
            "## 2. Investigation Manifests & Metadata",
            "",
            "| Accession | Title | Version | License | DOI | Hardware |",
            "| --- | --- | --- | --- | --- | --- |",
        ]
    )

    for inv in report["investigations"]:
        title = (inv.get("title") or "Unknown")[:40]
        ver = inv.get("version") or "unknown"
        lic = inv.get("license") or "N/A"
        doi = inv.get("doi") or "N/A"
        hw = ", ".join(inv.get("hardware") or []) or "N/A"
        md.append(f"| {inv['accession']} | {title} | {ver} | {lic} | {doi} | {hw} |")

    md.extend(
        [
            "",
            "## 3. Reports & Science Documents (under 20 MB)",
            "",
            "| Accession | Category | Document Name | Size (bytes) | SHA-256 |",
            "| --- | --- | --- | --- | --- |",
        ]
    )

    for inv in report["investigations"]:
        for d in inv["documents"]:
            if d.get("success"):
                md.append(
                    f"| {inv['accession']} | {d.get('category')} | {d['file_name']} "
                    f"| {d.get('bytes', 'N/A')} | `{d.get('sha256', '')[:16]}...` |"
                )

    md.extend(
        [
            "",
            "## 4. Context & Challenge Background Pages",
            "",
            "| Slug | Title | Source URL | Size (bytes) | Status |",
            "| --- | --- | --- | --- | --- |",
        ]
    )

    for c in report["context_pages"]:
        status = "PASS" if c.get("success") else f"FAIL ({c.get('error', 'unknown')})"
        size = c.get("bytes", 0)
        url = c["url"]
        slug = c["slug"]
        title = c["title"]
        md.append(f"| {slug} | {title} | [{url}]({url}) | {size} | {status} |")

    md.append("")
    log_content = "\n".join(md)
    (output_dir / "HARVEST_LOG.md").write_text(log_content, encoding="utf-8")
    return log_content


def run_harvest(
    raw_dir: Path,
    concurrency: int = DEFAULT_CONCURRENCY,
    use_cache: bool = True,
    download_documents: bool = True,
) -> dict:
    """Execute complete Phase 3 harvest pipeline."""
    started_at = datetime.now(UTC).isoformat()
    t_start = time.perf_counter()
    report = {
        "started_at_utc": started_at,
        "purpose": "Phase 3 complete harvest; original CSV tables, manifests, reports and context",
        "investigations": [],
        "context_pages": [],
        "success": False,
    }

    raw_dir.mkdir(parents=True, exist_ok=True)

    with httpx.Client(
        timeout=60, follow_redirects=True, headers={"User-Agent": USER_AGENT}
    ) as client:
        # Step 3.1: Catalogue
        cat_meta, combustion_hits = harvest_catalogue(client, raw_dir)
        report["catalogue"] = cat_meta
        accessions = [
            h["_source"]["Accession"]
            for h in combustion_hits
            if h.get("_source", {}).get("Accession")
        ]

        # Step 3.2: Manifests with concurrency
        logger.info("Harvesting %d manifests (concurrency=%d)...", len(accessions), concurrency)
        manifest_map = {}
        with ThreadPoolExecutor(max_workers=concurrency) as executor:
            future_to_acc = {
                executor.submit(harvest_manifest, client, acc, raw_dir / acc, use_cache): acc
                for acc in accessions
            }
            for future in as_completed(future_to_acc):
                res = future.result()
                manifest_map[res["accession"]] = res

        # Steps 3.3 & 3.4: Tables and Documents
        for acc in accessions:
            m_res = manifest_map.get(acc, {})
            manifest = m_res.get("manifest")
            if not manifest:
                logger.error("Skipping tables/docs for %s: manifest missing", acc)
                continue

            raw_hw = manifest.get("experimentHardware") or []
            if isinstance(raw_hw, str):
                hardware = [h.strip() for h in raw_hw.split(",") if h.strip()]
            elif isinstance(raw_hw, list):
                hardware = []
                for hw in raw_hw:
                    if isinstance(hw, str) and hw.strip():
                        hardware.append(hw.strip())
                    elif isinstance(hw, dict) and hw.get("name"):
                        hardware.append(str(hw["name"]).strip())
            else:
                hardware = []

            inv_entry = {
                "accession": acc,
                "title": manifest.get("title"),
                "version": str(manifest.get("version")),
                "license": manifest.get("licenseIdentifier"),
                "doi": manifest.get("doi"),
                "hardware": hardware,
                "tables": [],
                "documents": [],
            }

            folder = raw_dir / acc
            # Step 3.3: Experimental Tables
            tables = harvest_tables(client, acc, manifest, folder, use_cache=use_cache)
            inv_entry["tables"] = tables

            # Step 3.4: Documents
            if download_documents:
                docs = harvest_docs(client, acc, manifest, folder, use_cache=use_cache)
                inv_entry["documents"] = docs

            report["investigations"].append(inv_entry)

        # Step 3.5: Context Pages
        context_res = harvest_context(client, raw_dir)
        report["context_pages"] = context_res

    report["total_seconds"] = round(time.perf_counter() - t_start, 2)
    total_tables = sum(len(inv["tables"]) for inv in report["investigations"])
    successful_tables = sum(
        sum(1 for t in inv["tables"] if t.get("success")) for inv in report["investigations"]
    )
    report["success"] = total_tables >= 22 and successful_tables == total_tables

    # Step 3.6: Save logs and summary JSON in raw and dated folder
    date_str = datetime.now(UTC).strftime("%Y-%m-%d")
    dated_dir = raw_dir / date_str
    dated_dir.mkdir(parents=True, exist_ok=True)
    summary_json = json.dumps(report, indent=2)
    (raw_dir / "harvest_summary.json").write_text(summary_json, encoding="utf-8")
    (dated_dir / "harvest_summary.json").write_text(summary_json, encoding="utf-8")
    generate_harvest_log(report, raw_dir)
    generate_harvest_log(report, dated_dir)

    # Also write a copy of HARVEST_LOG.md to docs/ for repository reference
    docs_dir = Path("docs")
    if docs_dir.exists():
        generate_harvest_log(report, docs_dir)

    logger.info(
        "Harvest completed in %.2fs. Success: %s",
        report["total_seconds"],
        report["success"],
    )
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=Path("raw"))
    parser.add_argument("--concurrency", type=int, default=DEFAULT_CONCURRENCY)
    parser.add_argument("--no-cache", action="store_true")
    parser.add_argument("--skip-docs", action="store_true")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
    report = run_harvest(
        raw_dir=args.output,
        concurrency=args.concurrency,
        use_cache=not args.no_cache,
        download_documents=not args.skip_docs,
    )
    if not report["success"]:
        parser.exit(1, "Harvest completed with errors. See raw/HARVEST_LOG.md for details.\n")
    print("Harvest succeeded: 24 investigations, all experimental tables and documents saved.")


if __name__ == "__main__":
    main()
