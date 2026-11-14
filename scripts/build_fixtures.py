"""Create Phase 2 fixtures from real public NASA metadata; no invented test measurements."""

import argparse
import hashlib
import json
import re
from datetime import UTC, datetime
from pathlib import Path

import httpx

from api.config import ROOT
from api.models import (
    Citation,
    Finding,
    Investigation,
    MetaResponse,
    Provenance,
    Publication,
    SourceDocument,
)
from harvest.spike import BASE_URL, USER_AGENT, fetch

ACCESSIONS = ("PSI-26", "PSI-69", "PSI-159", "PSI-100", "PSI-25")
SAMPLE = ROOT / "snapshots/sample"


def build(source_dir: Path | None = None) -> None:
    now = datetime.now(UTC)
    SAMPLE.mkdir(parents=True, exist_ok=True)
    records = []
    inventory = []
    old_inventory_path = ROOT / "docs/context/source-inventory.json"
    old_inventory = (
        {i["accession"]: i for i in json.loads(old_inventory_path.read_text())}
        if old_inventory_path.exists()
        else {}
    )
    with httpx.Client(
        timeout=45, follow_redirects=True, headers={"User-Agent": USER_AGENT}
    ) as client:
        for accession in ACCESSIONS:
            url = BASE_URL + "/geode-py/ws/repo/investigations/" + accession
            content = (
                (source_dir / accession / "manifest.json").read_bytes()
                if source_dir
                else fetch(client, url).content
            )
            data = json.loads(content)
            raw_file = ROOT / "raw/fixtures" / accession / "manifest.json"
            raw_file.parent.mkdir(parents=True, exist_ok=True)
            raw_file.write_bytes(content)
            checksum = hashlib.sha256(content).hexdigest()
            previous = old_inventory.get(accession, {})
            retrieved = (
                datetime.fromisoformat(previous["retrieved_at"])
                if source_dir and previous.get("manifest_sha256") == checksum
                else now
            )
            version = str(data.get("version", "unknown"))
            title = data["title"]
            unique_files = {
                file["file_name"]: file
                for file in [*(data.get("added") or []), *(data.get("experimentalTable") or [])]
                if file.get("file_name")
            }
            provenance = Provenance(
                source_url=url,
                source_file="manifest.json",
                source_version=version,
                retrieved_at=retrieved,
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
                doi=data.get("doi") or None,
                description=data.get("description") or None,
                objectives=data.get("objective") or None,
                approach=data.get("approach") or None,
                hypothesis=data.get("hypothesis") or None,
                research_impacts=data.get("researchImpacts") or None,
                sub_area=data.get("subResearchArea") or None,
                hardware=[data["experimentHardware"]] if data.get("experimentHardware") else [],
                platform=data.get("flightProgram") or None,
                related_investigations=re.findall(r"PSI-\d+", data.get("related_glds") or ""),
                file_count=len(unique_files),
                file_size_bytes=(
                    sum(int(file["file_size"]) for file in unique_files.values())
                    if unique_files
                    and all(file.get("file_size") is not None for file in unique_files.values())
                    else None
                ),
                publications=[
                    Publication(
                        title=publication["title"],
                        authors=publication.get("authorList") or None,
                        doi=publication.get("doi") or None,
                    )
                    for publication in data.get("publications") or []
                    if publication.get("title")
                ],
                documents=[
                    SourceDocument(
                        name=file["file_name"],
                        url=BASE_URL + "/physci/repo/data/investigations/" + accession,
                        size_bytes=int(file["file_size"])
                        if file.get("file_size") is not None
                        else None,
                    )
                    for file in data.get("added") or []
                    if any(
                        category in file.get("file_name", "")
                        for category in ["_Reports_", "_Science Documents_"]
                    )
                ],
                version=version,
                license=data.get("licenseIdentifier") or None,
                source_url=BASE_URL + "/physci/repo/data/investigations/" + accession,
                retrieved_at=retrieved,
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
                    "retrieved_at": retrieved.isoformat(),
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
        snapshot_id="plan-aligned-metadata-fixture-v2",
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
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--fetch", action="store_true", help="Explicitly refresh NASA metadata")
    group.add_argument(
        "--from-cache", type=Path, help="Use retained manifests without network access"
    )
    args = parser.parse_args()
    build(args.from_cache)


if __name__ == "__main__":
    main()
