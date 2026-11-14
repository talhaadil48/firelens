"""Create Phase 2 fixtures from real public NASA metadata; no invented test measurements."""

import argparse
import hashlib
import json
from datetime import UTC, datetime

import httpx

from api.config import ROOT
from api.models import Citation, Finding, Investigation, MetaResponse, Provenance
from harvest.spike import BASE_URL, USER_AGENT, fetch

ACCESSIONS = ("PSI-26", "PSI-69", "PSI-159", "PSI-100", "PSI-25")
SAMPLE = ROOT / "snapshots/sample"


def build() -> None:
    now = datetime.now(UTC)
    SAMPLE.mkdir(parents=True, exist_ok=True)
    records = []
    inventory = []
    with httpx.Client(
        timeout=45, follow_redirects=True, headers={"User-Agent": USER_AGENT}
    ) as client:
        for accession in ACCESSIONS:
            url = BASE_URL + "/geode-py/ws/repo/investigations/" + accession
            content = fetch(client, url).content
            data = json.loads(content)
            raw_file = ROOT / "raw/fixtures" / accession / "manifest.json"
            raw_file.parent.mkdir(parents=True, exist_ok=True)
            raw_file.write_bytes(content)
            checksum = hashlib.sha256(content).hexdigest()
            version = str(data.get("version", "unknown"))
            title = data["title"]
            provenance = Provenance(
                source_url=url,
                source_file="manifest.json",
                source_version=version,
                retrieved_at=now,
                source_sha256=checksum,
            )
            citation = Citation(
                id=accession + ":catalogue-title",
                accession=accession,
                locator="title",
                supporting_text=title,
                provenance=provenance,
            )
            record = Investigation(
                accession=accession,
                title=title,
                acronym=data.get("investigationAcronym") or None,
                research_area=data.get("researchArea") or "Combustion Science",
                version=version,
                license=data.get("licenseIdentifier") or None,
                source_url=BASE_URL + "/physci/repo/data/investigations/" + accession,
                retrieved_at=now,
                fixture=True,
                citations=[citation],
                findings=[
                    Finding(
                        claim=f"NASA catalogue title: {title}",
                        evidence_type="metadata",
                        citation_ids=[citation.id],
                    )
                ],
            )
            records.append(record.model_dump(mode="json"))
            inventory.append(
                {
                    "accession": accession,
                    "title": title,
                    "source_url": url,
                    "retrieved_at": now.isoformat(),
                    "version": version,
                    "license": data.get("licenseIdentifier"),
                    "manifest_sha256": checksum,
                    "experimental_table_files": [
                        {"name": table.get("file_name"), "size_bytes": table.get("file_size")}
                        for table in data.get("experimentalTable") or []
                    ],
                }
            )
    payload = {"items": records, "total": len(records), "limit": 100, "offset": 0, "mode": "mock"}
    (SAMPLE / "investigations.json").write_text(json.dumps(payload, indent=2) + "\n")
    meta = MetaResponse(
        snapshot_id="phase2-metadata-fixture-v1",
        snapshot_date=now,
        investigation_count=len(records),
        test_count=0,
        warnings=[
            (
                "Phase 2 contract fixtures: real NASA titles and metadata; "
                "scientific claims unreviewed."
            ),
            "No normalized test measurements or mission-safety rankings are available yet.",
        ],
    )
    (SAMPLE / "meta.json").write_text(meta.model_dump_json(indent=2) + "\n")
    (SAMPLE / "tests.json").write_text(
        json.dumps({"items": [], "total": 0, "limit": 100, "offset": 0, "mode": "mock"}, indent=2)
        + "\n"
    )
    (ROOT / "docs/context/source-inventory.json").write_text(json.dumps(inventory, indent=2) + "\n")
    print(f"Built {len(records)} real-metadata fixtures; 0 normalized measurements (intentional).")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--fetch", action="store_true", help="Explicitly refresh NASA metadata")
    if not parser.parse_args().fetch:
        parser.exit(2, "Network refresh requires --fetch. Existing fixtures work offline.\n")
    build()


if __name__ == "__main__":
    main()
