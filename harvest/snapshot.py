"""Phase 5: precompute investigation facts and write a dated snapshot.

snapshots/<id>/
    tests.parquet        normalized test rows (one per test, provenance flattened)
    investigations.json  InvestigationList for every Combustion Science investigation
    chunks.jsonl         text chunks for retrieval (catalogue fields, report pages, context)
    snapshot.json        machine-readable identity, counts and per-accession versions
    SNAPSHOT.md          human-readable summary
snapshots/latest.json    pointer to the live snapshot
Numbers come from code; nothing here calls a language model.
"""

import json
import re
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path

import pandas as pd
import yaml

from api.models import (
    Citation,
    ConditionRange,
    ExperimentalTest,
    Investigation,
    InvestigationList,
    Provenance,
    ReviewStatus,
    SourceDocument,
)
from harvest import psi
from harvest.documents import MEDIA_TYPES, extract
from harvest.normalize import HARVEST_DIR, TableResult, load_maps, normalize_all
from harvest.validation import validate_tests

CURATION_FILE = HARVEST_DIR / "curation.yaml"
CHUNK_CHARS = 2400  # roughly 500-600 tokens
RANGE_FIELDS = {"o2_fraction": "fraction", "pressure_kpa": "kPa", "flow_cm_s": "cm/s"}


def tests_frame(rows: list[ExperimentalTest]) -> pd.DataFrame:
    records = []
    for row in rows:
        data = row.model_dump(mode="json")
        provenance = data.pop("provenance")
        data["metrics"] = json.dumps(data["metrics"], ensure_ascii=False)
        data["notes"] = json.dumps(data["notes"], ensure_ascii=False)
        records.append({**data, **{k: provenance[k] for k in provenance if k != "page"}})
    frame = pd.DataFrame.from_records(records)
    for column in ["o2_fraction", "pressure_kpa", "flow_cm_s", "sample_size_mm"]:
        frame[column] = pd.to_numeric(frame[column]).astype("float64")
    frame["test_date"] = pd.to_datetime(frame["test_date"]).dt.date
    frame["source_row"] = frame["source_row"].astype("int64")
    return frame


def fire_safety_tags(text: str, keywords: dict[str, list[str]]) -> list[str]:
    lowered = text.lower()
    return [tag for tag, stems in keywords.items() if any(stem in lowered for stem in stems)]


def condition_ranges(rows: list[ExperimentalTest]) -> dict[str, ConditionRange]:
    ranges = {}
    for name, unit in RANGE_FIELDS.items():
        values = [getattr(r, name) for r in rows if getattr(r, name) is not None]
        if values:
            ranges[name] = ConditionRange(minimum=min(values), maximum=max(values), unit=unit)
    return ranges


def split_text(text: str, size: int = CHUNK_CHARS) -> list[str]:
    paragraphs = [p.strip() for p in re.split(r"\n+", text) if p.strip()]
    chunks, current = [], ""
    for paragraph in paragraphs:
        if current and len(current) + len(paragraph) + 1 > size:
            chunks.append(current)
            current = ""
        while len(paragraph) > size:  # very long paragraph: cut at a sentence end
            cut = paragraph.rfind(". ", 0, size)
            cut = cut + 1 if cut > size // 2 else size
            chunks.append(paragraph[:cut].strip())
            paragraph = paragraph[cut:].strip()
        current = f"{current}\n{paragraph}".strip()
    if current:
        chunks.append(current)
    return chunks


def build_investigations(
    report: dict, rows_by_accession: dict, review_by_accession: dict, curation: dict
) -> list[Investigation]:
    retrieved_at = report["retrieved_at"]
    items = []
    for entry in report["investigations"]:
        cat, man = entry["catalogue"], entry.get("manifest")
        accession = cat["accession"]
        if not man:
            continue
        rows = rows_by_accession.get(accession, [])
        tables = [t for t in entry.get("tables", []) if t["success"]]
        if accession in curation["fire_safety_tags"]:
            tags = curation["fire_safety_tags"][accession]
        else:
            text = " ".join([cat["title"], cat["sub_area"] or "", " ".join(cat["keywords"])])
            tags = fire_safety_tags(text, curation["fire_safety_keywords"])
        if rows:
            fuel_phase = Counter(r.fuel_phase for r in rows).most_common(1)[0][0]
        else:
            fuel_phase = curation["fuel_phase"].get(accession, "unknown")
        review = review_by_accession.get(accession)
        if review == "reviewed":
            data_status = "reviewed"
        elif rows:
            data_status = "normalized"
        elif tables:
            data_status = "raw_downloaded"
        else:
            data_status = "metadata_only"
        citation = Citation(
            id=f"{accession}:catalogue",
            accession=accession,
            locator=f"PSI catalogue and investigation record, version {man['version']}",
            supporting_text=cat["title"],
            provenance=Provenance(
                source_url=man["url"],
                source_file="manifest.json",
                source_version=man["version"],
                retrieved_at=retrieved_at,
                source_sha256=man["sha256"],
            ),
        )
        size = man.get("total_size_bytes")
        docs = [d for d in entry.get("documents", []) if d["success"]]
        file_counts = man.get("file_counts") or {"Experimental table": len(entry.get("tables", []))}
        items.append(
            Investigation(
                accession=accession,
                title=cat["title"],
                acronym=cat["acronym"],
                research_area=cat["research_area"],
                sub_area=man.get("sub_area") or cat["sub_area"],
                description=man.get("description"),
                objectives=cat["objectives"] or man.get("objective"),
                approach=cat["approach"],
                hypothesis=cat["hypothesis"],
                research_impacts=cat["research_impacts"],
                keywords=cat["keywords"],
                publications=[
                    p["title"] + (f" (doi:{p['doi']})" if p.get("doi") else "")
                    for p in man.get("publications", [])
                ],
                doi=man["doi"],
                version=man["version"],
                license=man["license"],
                source_url=man["page_url"],
                retrieved_at=retrieved_at,
                hardware=[man["hardware"]] if man.get("hardware") else [],
                platform=cat["platform"],
                fuel_phase=fuel_phase,
                fire_safety_tags=tags,
                condition_ranges=condition_ranges(rows),
                documents=[
                    SourceDocument(
                        name=t["file"],
                        url=man["page_url"],
                        media_type="text/csv",
                        size_bytes=t.get("bytes"),
                    )
                    for t in tables
                ]
                + [
                    # Linked to the PSI page, never to a copy on our server.
                    SourceDocument(
                        name=d["file"],
                        url=man["page_url"],
                        media_type=MEDIA_TYPES.get(Path(d["file"]).suffix.lower()),
                        size_bytes=d.get("bytes"),
                    )
                    for d in docs
                ],
                related_investigations=[a for a in cat["related"] if a != accession],
                citations=[citation],
                test_count=len(rows),
                file_counts=file_counts,
                total_size_bytes=int(float(size)) if size not in (None, "", "None") else None,
                review_status=ReviewStatus.REVIEWED
                if review == "reviewed"
                else ReviewStatus.UNREVIEWED,
                data_status=data_status,
                fixture=False,
            )
        )
    items.sort(key=lambda i: int(i.accession.split("-")[1]))
    return items


def build_chunks(investigations: list[Investigation], raw_dir: Path) -> list[dict]:
    chunks = []
    for inv in investigations:
        fields = {
            "Objectives": inv.objectives,
            "Approach": inv.approach,
            "Hypothesis": inv.hypothesis,
            "Research Impacts/Earth Benefits": inv.research_impacts,
        }
        for label, text in fields.items():
            for n, part in enumerate(split_text(text or ""), start=1):
                chunks.append(
                    {
                        "id": f"{inv.accession}:catalogue:{label}:{n}",
                        "kind": "catalogue",
                        "accession": inv.accession,
                        "acronym": inv.acronym,
                        "doi": inv.doi,
                        "version": inv.version,
                        "source_file": f"PSI catalogue: {label}",
                        "page": None,
                        "url": str(inv.source_url),
                        "text": f"{inv.acronym or inv.title} ({inv.accession}) {label}: {part}",
                    }
                )
    for path in (
        sorted((raw_dir / "context").glob("*.txt")) if (raw_dir / "context").exists() else []
    ):
        content = path.read_text(encoding="utf-8")
        url = content.splitlines()[0].removeprefix("SOURCE: ").strip()
        body = content.split("\n", 2)[-1]
        if len(body) < 200:  # JS-rendered pages scrape to almost nothing; skip
            continue
        for n, part in enumerate(split_text(body), start=1):
            chunks.append(
                {
                    "id": f"context:{path.stem}:{n}",
                    "kind": "context",
                    "accession": None,
                    "acronym": None,
                    "doi": None,
                    "version": None,
                    "source_file": path.stem,
                    "page": None,
                    "url": url,
                    "text": part,
                }
            )
    return chunks


def document_chunks(
    investigations: list[Investigation], raw_dir: Path, report: dict
) -> tuple[list[dict], list[dict]]:
    """Report/science-document text, chunked within each page so every chunk has one page."""
    by_id = {inv.accession: inv for inv in investigations}
    chunks, stats = [], []
    for entry in report["investigations"]:
        inv = by_id.get(entry["catalogue"]["accession"])
        if inv is None:
            continue
        for doc in entry.get("documents", []):
            if not doc["success"]:
                continue
            text = extract(raw_dir / inv.accession / "documents" / doc["file"])
            stat = {
                "accession": inv.accession,
                "file": doc["file"],
                "folder": doc["folder"],
                "pages": text.page_count,
                "text_pages": len(text.pages),
                "empty_pages": text.empty_pages,
                "chunks": 0,
                "error": text.error,
            }
            label = inv.acronym or inv.title
            for page, body in text.pages:
                where = f"p. {page}" if page else "document"
                for n, part in enumerate(split_text(body), start=1):
                    chunks.append(
                        {
                            "id": f"{inv.accession}:doc:{doc['file']}:{page or 0}:{n}",
                            "kind": "document",
                            "accession": inv.accession,
                            "acronym": inv.acronym,
                            "doi": inv.doi,
                            "version": inv.version,
                            "source_file": doc["file"],
                            "source_folder": doc["folder"],
                            "source_sha256": doc.get("sha256"),
                            "page": page,
                            "url": str(inv.source_url),
                            "text": f"{label} ({inv.accession}) {doc['file']}, {where}: {part}",
                        }
                    )
                    stat["chunks"] += 1
            stats.append(stat)
    return chunks, stats


def write_summary(
    path: Path, meta: dict, investigations, results: list[TableResult], doc_stats: list[dict]
) -> None:
    lines = [
        f"# Snapshot {meta['snapshot_id']}",
        "",
        f"- Created: {meta['created_at']}",
        f"- PSI retrieved: {meta['psi_retrieved_at']}",
        f"- Investigations: {meta['investigation_count']} (Combustion Science)",
        f"- Normalized tests: {meta['test_count']} "
        f"(reviewed: {meta['reviewed_test_count']}; unreviewed rows must not support "
        "mission-safety conclusions)",
        f"- Text chunks: {meta['chunk_count']} ({meta['chunk_kinds']})",
        f"- Documents read: {meta['document_count']}",
        "- Embeddings: none in this build (vectors/ is added by the embed step)",
        "- Source: NASA Physical Sciences Informatics (CC0-1.0). Cite each dataset by its DOI.",
        "",
        "## Normalized tables",
        "",
        "| Accession | File | Tests | Blank rows skipped |",
        "| --- | --- | --- | --- |",
    ]
    lines += [f"| {r.accession} | {r.file} | {len(r.rows)} | {r.blank_rows} |" for r in results]
    if doc_stats:
        lines += [
            "",
            "## Documents (text corpus)",
            "",
            "| Accession | File | Pages | Pages with text | Chunks | Note |",
            "| --- | --- | --- | --- | --- | --- |",
        ]
        lines += [
            f"| {d['accession']} | {d['file']} | {d['pages'] or '-'} | {d['text_pages']} | "
            f"{d['chunks']} | {d['error'] or ('no extractable text' if not d['chunks'] else '')} |"
            for d in doc_stats
        ]
    lines += [
        "",
        "## Investigations",
        "",
        "| Accession | Acronym | Version | DOI | Tests | Data status |",
        "| --- | --- | --- | --- | --- | --- |",
    ]
    lines += [
        f"| {i.accession} | {i.acronym or ''} | {i.version} | {i.doi or ''} | "
        f"{i.test_count} | {i.data_status} |"
        for i in investigations
    ]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def build(raw_dir: Path = Path("raw"), out_root: Path = Path("snapshots")) -> Path:
    report = json.loads((raw_dir / "harvest.json").read_text(encoding="utf-8"))
    curation = yaml.safe_load(CURATION_FILE.read_text(encoding="utf-8"))
    results = normalize_all(raw_dir)
    rows = [row for result in results for row in result.rows]
    validate_tests(rows)
    rows_by_accession: dict[str, list[ExperimentalTest]] = {}
    for row in rows:
        rows_by_accession.setdefault(row.accession, []).append(row)
    review_by_accession = {m["accession"]: m.get("review", {}).get("status") for m in load_maps()}
    investigations = build_investigations(report, rows_by_accession, review_by_accession, curation)
    chunks = build_chunks(investigations, raw_dir)
    doc_chunks, doc_stats = document_chunks(investigations, raw_dir, report)
    chunks += doc_chunks

    created = datetime.now(UTC)
    snapshot_id = created.strftime("%Y%m%dT%H%M%SZ")
    folder = out_root / snapshot_id
    folder.mkdir(parents=True, exist_ok=False)
    tests_frame(rows).to_parquet(folder / "tests.parquet", index=False)
    listing = InvestigationList(
        items=investigations, total=len(investigations), limit=100, offset=0, mode="snapshot"
    )
    (folder / "investigations.json").write_text(listing.model_dump_json(indent=2) + "\n")
    with (folder / "chunks.jsonl").open("w", encoding="utf-8") as handle:
        for chunk in chunks:
            handle.write(json.dumps(chunk, ensure_ascii=False) + "\n")
    meta = {
        "snapshot_id": snapshot_id,
        "created_at": created.isoformat(),
        "psi_retrieved_at": report["retrieved_at"],
        "catalogue_sha256": report["catalogue"]["sha256"],
        "investigation_count": len(investigations),
        "test_count": len(rows),
        "reviewed_test_count": sum(r.review_status == ReviewStatus.REVIEWED for r in rows),
        "chunk_count": len(chunks),
        "chunk_kinds": dict(Counter(c["kind"] for c in chunks)),
        "document_count": sum(1 for d in doc_stats if d["chunks"]),
        "versions": {i.accession: i.version for i in investigations},
        "psi_base_url": psi.BASE_URL,
    }
    (folder / "snapshot.json").write_text(json.dumps(meta, indent=2) + "\n", encoding="utf-8")
    write_summary(folder / "SNAPSHOT.md", meta, investigations, results, doc_stats)
    pointer = {"snapshot_id": snapshot_id, "path": f"{snapshot_id}/"}
    (out_root / "latest.json").write_text(json.dumps(pointer, indent=2) + "\n", encoding="utf-8")
    return folder
