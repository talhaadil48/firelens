"""Phase 2 source feasibility check. Saves original experimental tables, not normalized data.

Signed URLs are consumed immediately and NEVER written to disk or console.
"""

import argparse
import json
import time
from datetime import UTC, datetime
from pathlib import Path

import httpx

from harvest.psi import BASE_URL, USER_AGENT, csv_summary, fetch, read_signed_url

__all__ = ["BASE_URL", "USER_AGENT", "csv_summary", "fetch", "read_signed_url", "run"]


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
