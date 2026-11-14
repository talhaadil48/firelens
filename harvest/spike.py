"""Phase 2 source feasibility check. Saves original experimental tables, not normalized data.

Signed URLs are consumed immediately and NEVER written to disk or console.
"""

import argparse
import csv
import hashlib
import io
import json
import time
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import urlsplit

import httpx

BASE_URL = "https://psi.nasa.gov"
USER_AGENT = "FireLens/0.1 NASA-Space-Apps-source-feasibility-check"


def read_signed_url(text: str) -> str:
    """PSI returns text, sometimes quoted; preserve the complete query string."""
    value = text.strip()
    if value.startswith('"'):
        value = json.loads(value)
    elif value.startswith("'") and value.endswith("'"):
        value = value[1:-1]
    parsed = urlsplit(value)
    host = parsed.hostname or ""
    if parsed.scheme != "https" or not (host == "psi.nasa.gov" or host.endswith(".amazonaws.com")):
        raise ValueError("PSI resolver did not return an expected HTTPS download URL")
    return value


def csv_summary(content: bytes) -> dict:
    encoding = "utf-8-sig"
    try:
        text = content.decode(encoding)
    except UnicodeDecodeError:
        # FLEX is a legacy Windows export (e.g. en dash byte 0x96).
        # Preserve bytes on disk and record the explicit decoding choice.
        encoding = "cp1252"
        text = content.decode(encoding)
    if text.lstrip().lower().startswith(("<!doctype", "<html", "<?xml", "<error")):
        raise ValueError("Expected CSV, received HTML/XML")
    rows = list(csv.reader(io.StringIO(text)))
    if not rows or len(rows[0]) < 2:
        raise ValueError("Expected a nonempty table with multiple columns")
    return {
        "headers": rows[0],
        "physical_data_rows": max(0, len(rows) - 1),
        "sha256": hashlib.sha256(content).hexdigest(),
        "bytes": len(content),
        "encoding": encoding,
    }


def fetch(client: httpx.Client, url: str, *, params: dict | None = None) -> httpx.Response:
    """Retry temporary failures; never include URLs containing signatures in errors."""
    for attempt in range(3):
        try:
            response = client.get(url, params=params)
            if response.status_code in (429, 500, 502, 503, 504) and attempt < 2:
                time.sleep(2**attempt)
                continue
            response.raise_for_status()
            return response
        except httpx.TransportError:
            if attempt == 2:
                raise
            time.sleep(2**attempt)
    raise RuntimeError("Retry loop exhausted")


def run(output: Path, report_path: Path) -> dict:
    output.mkdir(parents=True, exist_ok=True)
    report = {
        "tested_at_utc": datetime.now(UTC).isoformat(),
        "purpose": "Phase 2 feasibility; downloaded rows are unreviewed, not normalized tests",
        "checks": [],
        "success": False,
    }
    started = time.perf_counter()
    with httpx.Client(
        timeout=45, follow_redirects=True, headers={"User-Agent": USER_AGENT}
    ) as client:
        t0 = time.perf_counter()
        catalogue = fetch(
            client,
            BASE_URL + "/geode-py/ws/repo/search",
            params={
                "term": "combustion",
                "source": "psi",
                "type": "investigation",
                "size": 100,
            },
        ).json()
        (output / "catalogue.json").write_text(json.dumps(catalogue, indent=2))
        hits = catalogue.get("hits", {}).get("hits", [])
        combustion = [
            h for h in hits if h.get("_source", {}).get("Research Area") == "Combustion Science"
        ]
        total = catalogue.get("hits", {}).get("total")
        report["catalogue"] = {
            "url": BASE_URL
            + "/geode-py/ws/repo/search?term=combustion&source=psi&type=investigation&size=100",
            "total_matches": total,
            "returned_records": len(hits),
            "combustion_records": len(combustion),
            "seconds": round(time.perf_counter() - t0, 3),
        }
        print(f"Catalogue: {len(combustion)} combustion investigations ({len(hits)} search hits)")
        for accession in ("PSI-69", "PSI-159"):
            folder = output / accession
            folder.mkdir(exist_ok=True)
            t0 = time.perf_counter()
            metadata_url = BASE_URL + "/geode-py/ws/repo/investigations/" + accession
            manifest = fetch(client, metadata_url).json()
            (folder / "manifest.json").write_text(json.dumps(manifest, indent=2))
            report["checks"].append(
                {
                    "accession": accession,
                    "kind": "manifest",
                    "url": metadata_url,
                    "title": manifest.get("title"),
                    "version": str(manifest.get("version")),
                    "license": manifest.get("licenseIdentifier"),
                    "seconds": round(time.perf_counter() - t0, 3),
                    "success": True,
                }
            )
            tables = manifest.get("experimentalTable") or []
            if not tables:
                report["checks"].append(
                    {
                        "accession": accession,
                        "kind": "csv",
                        "success": False,
                        "error": "No experimentalTable entries found",
                    }
                )
            for table in tables:
                name = table.get("file_name", "")
                if not name.lower().endswith(".csv"):
                    continue
                if Path(name).name != name:
                    raise ValueError("Unsafe source filename")
                check = {"accession": accession, "kind": "csv", "file": name, "success": False}
                t0 = time.perf_counter()
                try:
                    if table.get("restricted"):
                        raise ValueError("Source table is marked restricted")
                    resolved = fetch(
                        client,
                        BASE_URL + f"/geode-py/ws/studies/{accession}/download",
                        params={"file": name, "redirect": "false"},
                    )
                    signed_url = read_signed_url(resolved.text)
                    content = fetch(client, signed_url).content
                    details = csv_summary(content)
                    (folder / name).write_bytes(content)
                    check.update(details, success=True)
                    print(f"{accession}: {name}")
                    print("  Headers:", json.dumps(details["headers"]))
                    print(
                        f"  {details['physical_data_rows']} CSV rows "
                        "(including any unit/description rows)"
                    )
                except httpx.HTTPStatusError as exc:
                    check["error"] = f"HTTP {exc.response.status_code}; signed URL omitted"
                except httpx.TransportError:
                    check["error"] = "Network/timeout failure; signed URL omitted"
                except (ValueError, UnicodeError) as exc:
                    check["error"] = str(exc)
                check["seconds"] = round(time.perf_counter() - t0, 3)
                report["checks"].append(check)
                if not check["success"]:
                    print(f"{accession}: {name}: {check['error']}")
    csv_checks = [c for c in report["checks"] if c["kind"] == "csv"]
    report["success"] = len(csv_checks) >= 3 and all(c["success"] for c in csv_checks)
    report["total_seconds"] = round(time.perf_counter() - started, 3)
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(report, indent=2) + "\n")
    print(f"Report: {report_path}; success={report['success']}")
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=Path("raw/spike"))
    parser.add_argument("--report", type=Path, default=Path("docs/SPIKE_RESULTS.json"))
    args = parser.parse_args()
    try:
        report = run(args.output, args.report)
    except (httpx.HTTPError, ValueError) as exc:
        # Do not stringify HTTP errors: they may embed temporary signed credentials.
        parser.exit(
            1, f"Source check failed ({type(exc).__name__}); retry when NASA is reachable.\n"
        )
    if not report["success"]:
        parser.exit(1, "One or more experimental tables could not be downloaded. See the report.\n")


if __name__ == "__main__":
    main()
