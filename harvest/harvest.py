"""Phase 3 harvester: PSI catalogue -> manifests -> experimental tables (+ context pages).

Layout (all under the git-ignored ``raw/``):
    raw/catalogue.json            search response as received
    raw/PSI-<n>/manifest.json     investigation detail as received
    raw/PSI-<n>/<table>.csv       experimental tables, original bytes
    raw/PSI-<n>/documents/<file>  Reports and Science Documents (PDF/DOCX under 20 MB)
    raw/context/<slug>.txt        challenge context pages as text, with their URL
    raw/harvest.json              inventory: provenance, hashes, headers, failures
    raw/HARVEST_LOG.md            human-readable counts, failures and timings

Never downloads Raw Data folders. Signed URLs are never stored or printed.
"""

import argparse
import asyncio
import hashlib
import json
import re
import time
from datetime import UTC, datetime
from html.parser import HTMLParser
from pathlib import Path

import httpx

from harvest import psi

RAW = Path("raw")
CONCURRENCY = 4
COMBUSTION = "Combustion Science"
# Documents for the text corpus (build-steps 3.4). Everything else, Raw Data above all,
# is only linked from the PSI page.
DOC_FOLDERS = ("Reports", "Science Documents")
DOC_TYPES = {".pdf": b"%PDF", ".docx": b"PK"}  # extension -> leading bytes
DOC_MAX_BYTES = 20_000_000
MIN_CONTEXT_CHARS = 200  # less than this means the page did not scrape

# Challenge resource pages (plan: Data pipeline step 5). Text only; links are cited.
CONTEXT_PAGES = {
    "nasa-combustion-science": "https://www.nasa.gov/glenn/glenn-expertise-space-exploration/physical-sciences-program/combustion-science/",
    "researchers-guide-combustion": "https://www.nasa.gov/missions/station/a-researchers-guide-to-combustion-science/",
    "apollo-1-lessons": "https://sma.nasa.gov/sma-disciplines/accllp/apollo-1",
    "apollo-13-lessons": "https://sma.nasa.gov/sma-disciplines/accllp/apollo-13",
    "mir-fire": "https://www.nasa.gov/history/25-years-ago-fire-aboard-space-station-mir/",
    "spinoff-air-tanks": "https://spinoff.nasa.gov/node/9582",
    "spinoff-fire-detector": "https://spinoff.nasa.gov/node/9407",
    "spinoff-fire-attire": "https://spinoff.nasa.gov/node/9918",
}

# Catalogue (search) field -> investigation text field.
CATALOGUE_TEXT = {
    "Objectives": "objectives",
    "Approach": "approach",
    "Hypothesis": "hypothesis",
    "Research Impacts/Earth Benefits": "research_impacts",
}


def safe_name(name: str) -> str:
    if not name or Path(name).name != name or name.startswith("."):
        raise ValueError("Unsafe source filename")
    return name


def catalogue_record(source: dict) -> dict:
    """Keep the catalogue fields the snapshot needs, as received (whitespace-trimmed)."""
    record = {"accession": source.get("Accession"), "title": source.get("Title")}
    record["acronym"] = (source.get("Acronym") or "").strip() or None
    record["research_area"] = source.get("Research Area")
    record["sub_area"] = (source.get("SubResearch Area") or "").strip() or None
    record["platform"] = (source.get("Flight Platform") or "").strip() or None
    record["related"] = re.findall(r"PSI-\d+", source.get("Related Investigations") or "")
    record["keywords"] = [
        k.strip() for k in re.split(r"\s{3,}", source.get("Keywords") or "") if k.strip()
    ]
    record["publication_titles"] = [
        t.strip() for t in re.split(r"\s{3,}", source.get("Publication Title") or "") if t.strip()
    ]
    for key, field in CATALOGUE_TEXT.items():
        record[field] = (source.get(key) or "").strip() or None
    return record


async def get_manifest(
    client: httpx.AsyncClient, sem: asyncio.Semaphore, accession: str, refresh: bool
) -> tuple[dict, bytes, float]:
    folder = RAW / accession
    path = folder / "manifest.json"
    if path.exists() and not refresh:
        content = path.read_bytes()
        return json.loads(content), content, 0.0
    async with sem:
        t0 = time.perf_counter()
        content = (await psi.afetch(client, psi.manifest_url(accession))).content
        seconds = time.perf_counter() - t0
    folder.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)
    return json.loads(content), content, seconds


async def get_table(
    client: httpx.AsyncClient,
    sem: asyncio.Semaphore,
    accession: str,
    table: dict,
    refresh: bool,
) -> dict:
    name = safe_name(table.get("file_name", ""))
    entry = {"file": name, "size_bytes": table.get("file_size"), "success": False}
    if not name.lower().endswith(".csv"):
        entry["error"] = "Not a CSV table; linked only"
        return entry
    if str(table.get("restricted", "False")).lower() == "true":
        entry["error"] = "Marked restricted at source"
        return entry
    path = RAW / accession / name
    t0 = time.perf_counter()
    try:
        if path.exists() and not refresh and path.stat().st_size == table.get("file_size"):
            content = path.read_bytes()
            entry["cached"] = True
        else:
            async with sem:
                content = await psi.download_table(client, accession, name)
            path.write_bytes(content)
        entry.update(psi.csv_summary(content), success=True)
    except httpx.HTTPStatusError as exc:
        entry["error"] = f"HTTP {exc.response.status_code}; signed URL omitted"
    except httpx.TransportError:
        entry["error"] = "Network/timeout failure; signed URL omitted"
    except (ValueError, UnicodeError) as exc:
        entry["error"] = str(exc)
    entry["seconds"] = round(time.perf_counter() - t0, 3)
    return entry


def manifest_folder(entry: dict) -> str:
    """PSI folder of a manifest file: /Home/psi-data/PSI-<n>/<folder>/<file>."""
    parts = (entry.get("remote_path") or "").strip("/").split("/")
    return parts[3] if len(parts) >= 5 else "Other"


def folder_counts(manifest: dict) -> dict[str, int]:
    counts: dict[str, int] = {}
    for entry in manifest.get("added") or []:
        folder = manifest_folder(entry)
        counts[folder] = counts.get(folder, 0) + 1
    return dict(sorted(counts.items()))


def document_candidates(manifest: dict) -> list[dict]:
    """Reports and Science Documents worth reading: PDF/DOCX, public, under 20 MB."""
    picked = []
    for entry in manifest.get("added") or []:
        folder = manifest_folder(entry)
        name = entry.get("file_name") or ""
        size = int(float(entry.get("file_size") or 0))
        if (
            folder in DOC_FOLDERS
            and Path(name).suffix.lower() in DOC_TYPES
            and 0 < size < DOC_MAX_BYTES
            and str(entry.get("restricted", False)).lower() != "true"
            and entry.get("visible", True) is not False
        ):
            picked.append(
                {"file": name, "folder": folder, "size": size, "version": entry.get("version")}
            )
    return sorted(picked, key=lambda d: (d["folder"], d["file"]))


async def get_document(
    client: httpx.AsyncClient,
    sem: asyncio.Semaphore,
    accession: str,
    doc: dict,
    refresh: bool,
) -> dict:
    name = safe_name(doc["file"])
    entry = {
        "file": name,
        "folder": doc["folder"],
        "version": doc["version"],
        "size_bytes": doc["size"],
        "success": False,
    }
    path = RAW / accession / "documents" / name
    t0 = time.perf_counter()
    try:
        if path.exists() and not refresh and path.stat().st_size == doc["size"]:
            content = path.read_bytes()
            entry["cached"] = True
        else:
            async with sem:
                content = await psi.download_file(
                    client, accession, name, doc["version"], attempts=3
                )
            if not content.startswith(DOC_TYPES[path.suffix.lower()]):
                raise ValueError(f"Not a {path.suffix} file (unexpected leading bytes)")
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(content)
        entry.update(success=True, bytes=len(content), sha256=hashlib.sha256(content).hexdigest())
    except httpx.HTTPStatusError as exc:
        entry["error"] = f"HTTP {exc.response.status_code}; signed URL omitted"
    except httpx.TransportError:
        entry["error"] = "Network/timeout failure; signed URL omitted"
    except ValueError as exc:
        entry["error"] = str(exc)
    entry["seconds"] = round(time.perf_counter() - t0, 3)
    return entry


class _TextExtractor(HTMLParser):
    # Not "form": ASP.NET pages (sma.nasa.gov Apollo pages) wrap the whole body in one form.
    SKIP = {"script", "style", "nav", "header", "footer", "noscript", "svg"}

    def __init__(self) -> None:
        super().__init__()
        self.parts: list[str] = []
        self._skip = 0

    def handle_starttag(self, tag, attrs):
        if tag in self.SKIP:
            self._skip += 1
        elif tag in {"p", "br", "li", "h1", "h2", "h3", "h4", "tr", "div"}:
            self.parts.append("\n")

    def handle_endtag(self, tag):
        if tag in self.SKIP and self._skip:
            self._skip -= 1

    def handle_data(self, data):
        if not self._skip:
            self.parts.append(data)


def html_to_text(html: str) -> str:
    parser = _TextExtractor()
    parser.feed(html)
    lines = [re.sub(r"\s+", " ", line).strip() for line in "".join(parser.parts).splitlines()]
    return "\n".join(line for line in lines if len(line) > 1)


async def get_context(client: httpx.AsyncClient, sem: asyncio.Semaphore, slug: str, url: str):
    folder = RAW / "context"
    folder.mkdir(parents=True, exist_ok=True)
    try:
        async with sem:
            response = await psi.afetch(client, url, attempts=2)
        text = html_to_text(response.text)
        (folder / f"{slug}.txt").write_text(f"SOURCE: {url}\n\n{text}\n", encoding="utf-8")
        result = {"slug": slug, "url": url, "chars": len(text), "success": True}
        if len(text) < MIN_CONTEXT_CHARS:
            result.update(success=False, error=f"Only {len(text)} chars of text extracted")
        return result
    except httpx.HTTPError as exc:
        return {"slug": slug, "url": url, "success": False, "error": type(exc).__name__}


async def harvest(only: set[str] | None, refresh: bool, context: bool, docs: bool = True) -> dict:
    RAW.mkdir(exist_ok=True)
    started = time.perf_counter()
    sem = asyncio.Semaphore(CONCURRENCY)
    report: dict = {"retrieved_at": datetime.now(UTC).isoformat(), "investigations": []}
    async with psi.async_client() as client:
        t0 = time.perf_counter()
        response = await psi.afetch(
            client, psi.BASE_URL + psi.CATALOGUE_PATH, params=psi.CATALOGUE_PARAMS
        )
        (RAW / "catalogue.json").write_bytes(response.content)
        hits = response.json().get("hits", {}).get("hits", [])
        sources = [h.get("_source", {}) for h in hits]
        kept = [s for s in sources if s.get("Research Area") == COMBUSTION]
        if only:
            kept = [s for s in kept if s.get("Accession") in only]
        report["catalogue"] = {
            "url": psi.BASE_URL + psi.CATALOGUE_PATH,
            "params": psi.CATALOGUE_PARAMS,
            "hits": len(hits),
            "combustion": len(kept),
            "dropped": sorted(
                f"{s.get('Accession')} ({s.get('Research Area')})"
                for s in sources
                if s.get("Research Area") != COMBUSTION
            ),
            "sha256": hashlib.sha256(response.content).hexdigest(),
            "seconds": round(time.perf_counter() - t0, 3),
        }
        print(f"Catalogue: {len(kept)} combustion investigations ({len(hits)} hits)")

        accessions = [s["Accession"] for s in kept]
        manifests = await asyncio.gather(
            *(get_manifest(client, sem, a, refresh) for a in accessions), return_exceptions=True
        )
        for source, result in zip(kept, manifests, strict=True):
            accession = source["Accession"]
            item = {"catalogue": catalogue_record(source)}
            if isinstance(result, BaseException):
                item["error"] = f"Manifest failed ({type(result).__name__})"
                report["investigations"].append(item)
                print(f"{accession}: manifest FAILED")
                continue
            manifest, content, seconds = result
            item["manifest"] = {
                "url": psi.manifest_url(accession),
                "page_url": psi.page_url(accession),
                "sha256": hashlib.sha256(content).hexdigest(),
                "seconds": round(seconds, 3),
                "version": str(manifest.get("version")),
                "doi": manifest.get("doi") or None,
                "license": manifest.get("licenseIdentifier") or None,
                "hardware": manifest.get("experimentHardware") or None,
                "hardware_links": manifest.get("experimentHardwareLink") or None,
                "sub_area": manifest.get("subResearchArea") or None,
                "description": manifest.get("description") or None,
                "objective": manifest.get("objective") or None,
                "total_size_bytes": manifest.get("totalFileSize"),
                "file_counts": folder_counts(manifest),
                "release_date": manifest.get("releaseDate"),
                "modified_date": manifest.get("modifiedDate"),
                "publications": [
                    {"title": p.get("title"), "doi": p.get("doi") or None}
                    for p in manifest.get("publications") or []
                    if p.get("title")
                ],
            }
            tables = manifest.get("experimentalTable") or []
            item["tables"] = await asyncio.gather(
                *(get_table(client, sem, accession, t, refresh) for t in tables)
            )
            ok = sum(t["success"] for t in item["tables"])
            line = f"{accession}: v{item['manifest']['version']}, {ok}/{len(tables)} tables"
            if docs:
                candidates = document_candidates(manifest)
                item["documents"] = await asyncio.gather(
                    *(get_document(client, sem, accession, d, refresh) for d in candidates)
                )
                got = sum(d["success"] for d in item["documents"])
                line += f", {got}/{len(candidates)} documents"
            print(line)
            report["investigations"].append(item)

        if context:
            report["context"] = await asyncio.gather(
                *(get_context(client, sem, slug, url) for slug, url in CONTEXT_PAGES.items())
            )
    report["total_seconds"] = round(time.perf_counter() - started, 3)
    (RAW / "harvest.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    write_log(report)
    return report


def write_log(report: dict) -> None:
    items = report["investigations"]
    tables = [t for i in items for t in i.get("tables", [])]
    ok = [t for t in tables if t["success"]]
    docs = [d for i in items for d in i.get("documents", [])]
    docs_ok = [d for d in docs if d["success"]]
    lines = [
        "# Harvest log",
        "",
        f"- Retrieved: {report['retrieved_at']}",
        f"- Catalogue: {report['catalogue']['hits']} hits, "
        f"{report['catalogue']['combustion']} Combustion Science kept",
        f"- Dropped (other research areas): {', '.join(report['catalogue']['dropped']) or 'none'}",
        f"- Manifests: {sum('manifest' in i for i in items)}/{len(items)}",
        f"- Experimental tables: {len(ok)}/{len(tables)} downloaded, "
        f"{sum(t['physical_data_rows'] for t in ok)} physical CSV rows (not verified test counts)",
        f"- Documents (Reports, Science Documents; PDF/DOCX < 20 MB): {len(docs_ok)}/{len(docs)}, "
        f"{round(sum(d['bytes'] for d in docs_ok) / 1e6, 1)} MB",
        f"- Total time: {report['total_seconds']} s",
        "",
        "| Accession | Acronym | Version | DOI | Tables (ok/total) | CSV rows | Documents |",
        "| --- | --- | --- | --- | --- | --- | --- |",
    ]
    for i in sorted(items, key=lambda x: int(x["catalogue"]["accession"].split("-")[1])):
        c, m, t = i["catalogue"], i.get("manifest", {}), i.get("tables", [])
        d = i.get("documents", [])
        rows = sum(x.get("physical_data_rows", 0) for x in t if x["success"])
        lines.append(
            f"| {c['accession']} | {c['acronym'] or ''} | {m.get('version', '')} | "
            f"{m.get('doi') or ''} | {sum(x['success'] for x in t)}/{len(t)} | {rows} | "
            f"{sum(x['success'] for x in d)}/{len(d)} |"
        )
    failures = [
        (i["catalogue"]["accession"], f)
        for i in items
        for f in [*i.get("tables", []), *i.get("documents", [])]
    ]
    failures = [(a, f) for a, f in failures if not f["success"]]
    errors = [i for i in items if "error" in i]
    if failures or errors:
        lines += ["", "## Failures", ""]
        lines += [f"- {i['catalogue']['accession']}: {i['error']}" for i in errors]
        lines += [f"- {a} `{t['file']}`: {t.get('error')}" for a, t in failures]
    if "context" in report:
        lines += ["", "## Context pages", ""]
        lines += [
            f"- {c['slug']}: {'ok, ' + str(c['chars']) + ' chars' if c['success'] else c['error']}"
            f" ({c['url']})"
            for c in report["context"]
        ]
    (RAW / "HARVEST_LOG.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--only", nargs="*", help="Limit to these accessions, e.g. PSI-69")
    parser.add_argument("--refresh", action="store_true", help="Ignore the on-disk cache")
    parser.add_argument("--no-context", action="store_true", help="Skip context pages")
    parser.add_argument("--no-docs", action="store_true", help="Skip report/science documents")
    args = parser.parse_args()
    try:
        report = asyncio.run(
            harvest(
                set(args.only) if args.only else None,
                args.refresh,
                not args.no_context,
                not args.no_docs,
            )
        )
    except (httpx.HTTPError, ValueError) as exc:
        # Do not stringify HTTP errors: they may embed temporary signed credentials.
        parser.exit(1, f"Harvest failed ({type(exc).__name__}); retry when PSI is reachable.\n")
    print(f"Log: {RAW / 'HARVEST_LOG.md'}")
    if any("error" in i for i in report["investigations"]):
        parser.exit(1, "Some manifests failed; see the log. Re-run to resume from cache.\n")


if __name__ == "__main__":
    main()
