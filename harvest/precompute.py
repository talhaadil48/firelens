"""Phase 5 precomputation: condition ranges, summaries, chunking, embeddings, and snapshot."""

import hashlib
import json
import os
import re
import zipfile
from datetime import UTC, datetime
from pathlib import Path
from xml.etree import ElementTree

import httpx
import numpy as np
import pandas as pd
import pymupdf

from api.models import (
    Citation,
    ConditionRange,
    EvidenceType,
    ExperimentalTest,
    Finding,
    Investigation,
    InvestigationList,
    InvestigationSummary,
    Provenance,
    Publication,
    SnapshotPointer,
    SourceDocument,
    TextChunk,
)
from api.snapshot import write_tests_parquet
from harvest.maps_schema import ColumnMap

BASE_URL = "https://psi.nasa.gov"
DOCX_TEXT_NS = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
ACCESSION_RE = re.compile(r"PSI-\d+")
TOKEN_RE = re.compile(r"[a-z0-9]+")


def _extract_docx_text(path: Path) -> str:
    """Extract paragraph text from a .docx file using the Python standard library."""
    try:
        with zipfile.ZipFile(path) as archive:
            if "word/document.xml" not in archive.namelist():
                return ""
            xml_bytes = archive.read("word/document.xml")
        root = ElementTree.fromstring(xml_bytes)
        paragraphs = []
        for para in root.iter(f"{DOCX_TEXT_NS}p"):
            runs = [node.text for node in para.iter(f"{DOCX_TEXT_NS}t") if node.text]
            line = "".join(runs).strip()
            if line:
                paragraphs.append(line)
        return "\n".join(paragraphs)
    except Exception:
        return ""


def _extract_pdf_pages(path: Path) -> list[tuple[int, str]]:
    """Extract (1-based page number, text) pairs from a PDF using PyMuPDF."""
    pages: list[tuple[int, str]] = []
    try:
        with pymupdf.open(path) as doc:
            for idx, page in enumerate(doc, start=1):
                text = page.get_text("text").strip()
                if text:
                    pages.append((idx, text))
    except Exception:
        return []
    return pages


def _chunk_text(text: str, max_chars: int = 2400, overlap: int = 200) -> list[str]:
    """Split text into ~500-800 token segments without breaking small paragraphs."""
    cleaned = "\n".join(line.strip() for line in text.splitlines() if line.strip())
    if not cleaned:
        return []
    if len(cleaned) <= max_chars:
        return [cleaned]
    chunks: list[str] = []
    start = 0
    while start < len(cleaned):
        end = min(len(cleaned), start + max_chars)
        if end < len(cleaned):
            split_at = cleaned.rfind("\n", start + max_chars // 2, end)
            if split_at == -1:
                split_at = cleaned.rfind(" ", start + max_chars // 2, end)
            if split_at > start:
                end = split_at
        piece = cleaned[start:end].strip()
        if piece:
            chunks.append(piece)
        if end >= len(cleaned):
            break
        start = max(end - overlap, start + 1)
    return chunks


def _approx_tokens(text: str) -> int:
    return max(1, len(text.split()))


def _compute_condition_ranges(rows: list[ExperimentalTest]) -> dict[str, ConditionRange]:
    ranges: dict[str, ConditionRange] = {}
    specs = [
        ("oxygen", "o2_fraction", "fraction"),
        ("pressure", "pressure_kpa", "kPa"),
        ("flow", "flow_cm_s", "cm/s"),
    ]
    for key, attr, unit in specs:
        vals = [getattr(row, attr) for row in rows if getattr(row, attr) is not None]
        if vals:
            ranges[key] = ConditionRange(minimum=min(vals), maximum=max(vals), unit=unit)
    return ranges


def _infer_fire_safety_tags(
    title: str, objective: str | None, sub_area: str | None, hardware: list[str]
) -> list[str]:
    blob = " ".join([title, objective or "", sub_area or "", *hardware]).lower()
    tags: list[str] = []
    if any(k in blob for k in ("smoke", "aerosol", "detector", "same", "daft")):
        tags.append("detection")
    if any(k in blob for k in ("extinguish", "suppress", "bass", "flex", "saffire")):
        tags.append("suppression")
    if any(
        k in blob
        for k in ("flammab", "ignit", "flame", "fire", "spread", "cool flame", "combustion")
    ):
        tags.append("prevention")
    return tags or ["prevention"]


def _infer_fuel_phase(
    rows: list[ExperimentalTest],
    study_maps: list[ColumnMap],
    title: str,
    description: str | None,
) -> str:
    row_phases = {row.fuel_phase for row in rows if row.fuel_phase != "unknown"}
    if len(row_phases) == 1:
        return next(iter(row_phases))
    if len(row_phases) > 1:
        return "mixed"
    map_phases = {m.default_fuel_phase for m in study_maps if m.default_fuel_phase != "unknown"}
    if len(map_phases) == 1:
        return next(iter(map_phases))
    blob = f"{title} {description or ''}".lower()
    if any(k in blob for k in ("droplet", "heptane", "methanol", "liquid")):
        return "liquid"
    if any(k in blob for k in ("fabric", "solid", "pmma", "saffire", "aerosol")):
        return "solid"
    if any(k in blob for k in ("gaseous", "methane", "ethylene", "ethane", "coflow", "burner")):
        return "gas"
    return "unknown"


def _format_conditions_text(ranges: dict[str, ConditionRange]) -> str | None:
    parts = []
    if "oxygen" in ranges:
        r = ranges["oxygen"]
        parts.append(f"O2 fraction {r.minimum:.3g}–{r.maximum:.3g}")
    if "pressure" in ranges:
        r = ranges["pressure"]
        parts.append(f"pressure {r.minimum:.1f}–{r.maximum:.1f} kPa")
    if "flow" in ranges:
        r = ranges["flow"]
        parts.append(f"airflow {r.minimum:.1f}–{r.maximum:.1f} cm/s")
    return "; ".join(parts) if parts else None


def _data_gaps(
    rows: list[ExperimentalTest],
    harvest_entry: dict,
    study_maps: list[ColumnMap] | None = None,
) -> list[str]:
    gaps: list[str] = []
    if not rows:
        tables = [entry for entry in harvest_entry.get("files", []) if entry.get("role") == "table"]
        gaps.append(
            "No experimental table was imported. Measurements may still be present "
            "in reports or publications."
        )
        if tables:
            gaps.append(
                "The harvest lists tables but no records were imported; "
                "inspect the collection and mapping configuration."
            )
        return gaps
    if study_maps is not None:
        mapped_files = {m.source_file for m in study_maps}
        unmapped_files = sorted(
            {r.source_file for r in rows if r.source_file and r.source_file not in mapped_files}
        )
        if unmapped_files:
            gaps.append(
                f"No scalar column map is configured for {', '.join(unmapped_files)}; "
                "original source cells are retained as reported."
            )
    grouped = sum(row.record_kind != "individual_test" for row in rows)
    if grouped:
        gaps.append(
            f"{grouped} source records describe groups, sessions, references or notes. "
            "They are retained as reported and are not counted as individual tests."
        )
    missing_fields = []
    for field, label in (
        ("o2_fraction", "oxygen"),
        ("pressure_kpa", "pressure"),
        ("flow_cm_s", "airflow"),
    ):
        missing = sum(getattr(row, field) is None for row in rows)
        if missing:
            missing_fields.append(f"{label} ({missing}/{len(rows)} records)")
    if missing_fields:
        gaps.append(
            "Exact numeric values unavailable for "
            + ", ".join(missing_fields)
            + ". Original values, ranges and lists remain in Measurements."
        )
    return gaps


def build_investigations(
    raw_dir: Path,
    rows: list[ExperimentalTest],
    column_maps: list[ColumnMap],
) -> list[Investigation]:
    """Build grounded Investigation records with condition ranges and summaries."""
    rows_by_acc: dict[str, list[ExperimentalTest]] = {}
    for row in rows:
        rows_by_acc.setdefault(row.accession, []).append(row)
    maps_by_acc: dict[str, list[ColumnMap]] = {}
    for cmap in column_maps:
        maps_by_acc.setdefault(cmap.accession, []).append(cmap)

    report = (
        json.loads((raw_dir / "report.json").read_text(encoding="utf-8"))
        if (raw_dir / "report.json").exists()
        else {}
    )
    report_by_acc = {item["accession"]: item for item in report.get("investigations", [])}

    investigations: list[Investigation] = []
    for manifest_path in sorted(raw_dir.glob("PSI-*/manifest.json")):
        acc = manifest_path.parent.name
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        rep_entry = report_by_acc.get(acc, {})
        acc_rows = rows_by_acc.get(acc, [])
        test_rows = [row for row in acc_rows if row.record_kind == "individual_test"]
        acc_maps = maps_by_acc.get(acc, [])

        title = manifest["title"]
        version = str(manifest.get("version") or "1")
        doi = manifest.get("doi") or None
        source_url = f"{BASE_URL}/physci/repo/data/investigations/{acc}"
        manifest_url = f"{BASE_URL}/geode-py/ws/repo/investigations/{acc}"
        retrieved_raw = rep_entry.get("started_at") or report.get("started_at")
        retrieved_at = datetime.fromisoformat(retrieved_raw) if retrieved_raw else datetime.now(UTC)
        manifest_sha = hashlib.sha256(manifest_path.read_bytes()).hexdigest()

        title_cit = Citation(
            id=f"{acc}:title",
            accession=acc,
            locator="manifest.title",
            supporting_text=title,
            provenance=Provenance(
                source_url=manifest_url,
                source_file="manifest.json",
                source_version=version,
                retrieved_at=retrieved_at,
                source_sha256=manifest_sha,
                is_mock=False,
            ),
        )
        citations = [title_cit]
        findings: list[Finding] = [
            Finding(
                claim=f"NASA PSI investigation: {title}",
                evidence_type=EvidenceType.METADATA,
                citation_ids=[title_cit.id],
                uncertainty_label="reported",
            )
        ]

        objective_text = (manifest.get("objective") or "").strip() or None
        if objective_text:
            obj_cit = Citation(
                id=f"{acc}:objective",
                accession=acc,
                locator="manifest.objective",
                supporting_text=objective_text[:400],
                provenance=Provenance(
                    source_url=manifest_url,
                    source_file="manifest.json",
                    source_version=version,
                    retrieved_at=retrieved_at,
                    source_sha256=manifest_sha,
                    is_mock=False,
                ),
            )
            citations.append(obj_cit)
            findings.append(
                Finding(
                    claim=objective_text.split(".")[0].strip() + ".",
                    evidence_type=EvidenceType.AUTHOR_INTERPRETATION,
                    citation_ids=[obj_cit.id],
                    uncertainty_label="reported",
                )
            )

        ranges = _compute_condition_ranges(test_rows)
        if acc_rows:
            first_row = acc_rows[0]
            cond_text = _format_conditions_text(ranges) or f"{len(acc_rows)} normalized rows"
            table_cit = Citation(
                id=f"{acc}:tests",
                accession=acc,
                locator=f"{first_row.source_file} (n={len(acc_rows)})",
                supporting_text=f"Imported {len(acc_rows)} source records ({cond_text}).",
                provenance=first_row.provenance,
            )
            citations.append(table_cit)
            findings.append(
                Finding(
                    claim=(
                        f"Imported {len(acc_rows)} source records ({cond_text}). "
                        "Grouped records are not individual tests."
                    ),
                    evidence_type=EvidenceType.MEASUREMENT,
                    citation_ids=[table_cit.id],
                    uncertainty_label="reported",
                )
            )

        fuels = sorted({r.fuel for r in acc_rows if r.fuel})
        geometries = sorted({r.sample_geometry for r in acc_rows if r.sample_geometry})
        fuels_geo = None
        if fuels or geometries:
            fuels_geo = f"Fuels: {', '.join(fuels[:6])}" + (
                f"; Geometry: {', '.join(geometries)}" if geometries else ""
            )

        varied_fields = [
            label
            for label, attr in [
                ("fuel", "fuel"),
                ("O2 fraction", "o2_fraction"),
                ("pressure", "pressure_kpa"),
                ("airflow", "flow_cm_s"),
                ("sample size", "sample_size_mm"),
            ]
            if len({getattr(r, attr) for r in acc_rows if getattr(r, attr) is not None}) > 1
        ]
        varied_text = (
            "Varied across normalized rows: " + ", ".join(varied_fields) if varied_fields else None
        )

        hardware = [manifest["experimentHardware"]] if manifest.get("experimentHardware") else []
        sub_area = manifest.get("subResearchArea") or None
        unique_files = {
            f["file_name"]: f
            for f in [*(manifest.get("added") or []), *(manifest.get("experimentalTable") or [])]
            if f.get("file_name")
        }
        file_sizes = [
            int(f["file_size"]) for f in unique_files.values() if f.get("file_size") is not None
        ]

        summary = InvestigationSummary(
            objective=objective_text.split(".")[0].strip() if objective_text else title,
            fuels_and_geometry=fuels_geo,
            conditions_tested=_format_conditions_text(ranges),
            varied=varied_text,
            sensors=[],
            findings=findings,
        )

        investigations.append(
            Investigation(
                accession=acc,
                title=title,
                acronym=manifest.get("investigationAcronym") or None,
                research_area=manifest.get("researchArea") or "Combustion Science",
                description=manifest.get("description") or None,
                objectives=objective_text,
                approach=manifest.get("approach") or None,
                hypothesis=manifest.get("hypothesis") or None,
                research_impacts=manifest.get("researchImpacts") or None,
                sub_area=sub_area,
                file_count=len(unique_files),
                file_size_bytes=sum(file_sizes) if file_sizes else None,
                publications=[
                    Publication(
                        title=pub["title"],
                        authors=pub.get("authorList") or None,
                        doi=pub.get("doi") or None,
                    )
                    for pub in manifest.get("publications") or []
                    if pub.get("title")
                ],
                summary=summary,
                doi=doi,
                version=version,
                license=manifest.get("licenseIdentifier") or None,
                source_url=source_url,
                retrieved_at=retrieved_at,
                hardware=hardware,
                platform=manifest.get("flightProgram") or None,
                fuel_phase=_infer_fuel_phase(
                    acc_rows, acc_maps, title, manifest.get("description")
                ),
                fire_safety_tags=_infer_fire_safety_tags(title, objective_text, sub_area, hardware),
                condition_ranges=ranges,
                documents=[
                    SourceDocument(
                        name=f["file_name"],
                        url=source_url,
                        size_bytes=int(f["file_size"]) if f.get("file_size") is not None else None,
                    )
                    for f in manifest.get("added") or []
                    if any(
                        cat in (f.get("file_name") or "")
                        for cat in ("_Reports_", "_Science Documents_")
                    )
                ],
                related_investigations=[
                    rel
                    for rel in ACCESSION_RE.findall(manifest.get("related_glds") or "")
                    if rel != acc
                ],
                findings=findings,
                citations=citations,
                test_count=len(test_rows),
                record_count=len(acc_rows),
                data_gaps=[
                    *_data_gaps(acc_rows, rep_entry, acc_maps),
                    "Sensor details are not extracted here; consult the source documents.",
                ],
                data_status="normalized" if acc_rows else "raw_downloaded",
                fixture=False,
            )
        )
    return investigations


def build_chunks(raw_dir: Path, investigations: list[Investigation]) -> list[TextChunk]:
    """Create validated TextChunk items from investigation fields, docs, and context."""
    chunks: list[TextChunk] = []
    seen_ids: set[str] = set()

    def _add_chunk(**kwargs) -> None:
        chunk = TextChunk(**kwargs)
        if chunk.chunk_id in seen_ids:
            return
        seen_ids.add(chunk.chunk_id)
        chunks.append(chunk)

    for inv in investigations:
        field_pairs = [
            ("objectives", inv.objectives),
            ("approach", inv.approach),
            ("hypothesis", inv.hypothesis),
            ("research_impacts", inv.research_impacts),
            ("description", inv.description),
        ]
        for fname, val in field_pairs:
            if not val or not val.strip():
                continue
            for idx, piece in enumerate(_chunk_text(val)):
                _add_chunk(
                    chunk_id=f"{inv.accession}:field:{fname}:{idx}",
                    accession=inv.accession,
                    source_kind="investigation_field",
                    source_file="manifest.json",
                    source_url=inv.source_url,
                    source_version=inv.version,
                    doi=inv.doi,
                    field_name=fname,
                    text=piece,
                    token_count=_approx_tokens(piece),
                    sha256=hashlib.sha256(piece.encode("utf-8")).hexdigest(),
                )

        if inv.summary:
            summary_lines = [inv.summary.objective]
            if inv.summary.fuels_and_geometry:
                summary_lines.append(inv.summary.fuels_and_geometry)
            if inv.summary.conditions_tested:
                summary_lines.append(inv.summary.conditions_tested)
            if inv.summary.varied:
                summary_lines.append(inv.summary.varied)
            summary_text = "\n".join(summary_lines)
            _add_chunk(
                chunk_id=f"{inv.accession}:summary:0",
                accession=inv.accession,
                source_kind="summary",
                source_file="investigations.json",
                source_url=inv.source_url,
                source_version=inv.version,
                doi=inv.doi,
                field_name="summary",
                text=summary_text,
                token_count=_approx_tokens(summary_text),
                sha256=hashlib.sha256(summary_text.encode("utf-8")).hexdigest(),
            )

        docs_dir = raw_dir / inv.accession / "documents"
        if docs_dir.exists():
            for doc_path in sorted(docs_dir.rglob("*")):
                if not doc_path.is_file():
                    continue
                suffix = doc_path.suffix.lower()
                doc_sha = hashlib.sha256(doc_path.read_bytes()).hexdigest()
                if suffix == ".pdf":
                    pages = _extract_pdf_pages(doc_path)
                elif suffix == ".docx":
                    txt = _extract_docx_text(doc_path)
                    pages = [(1, txt)] if txt else []
                else:
                    continue
                for page_num, page_text in pages:
                    for idx, piece in enumerate(_chunk_text(page_text)):
                        _add_chunk(
                            chunk_id=f"{inv.accession}:doc:{doc_sha[:10]}:p{page_num}:c{idx}",
                            accession=inv.accession,
                            source_kind="document",
                            source_file=doc_path.name,
                            source_url=inv.source_url,
                            source_version=inv.version,
                            doi=inv.doi,
                            page=page_num,
                            text=piece,
                            token_count=_approx_tokens(piece),
                            sha256=doc_sha,
                        )

    context_dir = raw_dir / "context"
    if context_dir.exists():
        for meta_path in sorted(context_dir.glob("*.source.json")):
            meta = json.loads(meta_path.read_text(encoding="utf-8"))
            text_path = context_dir / meta["text_file"]
            if not text_path.exists():
                continue
            txt = text_path.read_text(encoding="utf-8")
            sha = (meta.get("text_integrity") or {}).get("sha256")
            for idx, piece in enumerate(_chunk_text(txt)):
                _add_chunk(
                    chunk_id=f"context:{meta['id']}:c{idx}",
                    accession=None,
                    source_kind="context_page",
                    source_file=meta["text_file"],
                    source_url=meta["url"],
                    text=piece,
                    token_count=_approx_tokens(piece),
                    sha256=sha,
                )
    return chunks


def _local_hash_embeddings(texts: list[str], dim: int = 256) -> list[list[float]]:
    """Deterministic L2-normalized feature-hashing embeddings for offline snapshots."""
    vectors: list[list[float]] = []
    for text in texts:
        vec = np.zeros(dim, dtype=np.float32)
        tokens = TOKEN_RE.findall(text.lower())
        for tok in tokens:
            digest = hashlib.blake2b(tok.encode("utf-8"), digest_size=8).digest()
            idx = int.from_bytes(digest[:4], "little") % dim
            sign = 1.0 if (digest[4] & 1) == 0 else -1.0
            vec[idx] += sign
        norm = float(np.linalg.norm(vec))
        if norm > 0.0:
            vec /= norm
        vectors.append(vec.tolist())
    return vectors


def _azure_embeddings(texts: list[str], batch_size: int = 64) -> list[list[float]] | None:
    endpoint = os.environ.get("AZURE_OPENAI_ENDPOINT", "").rstrip("/")
    api_key = os.environ.get("AZURE_OPENAI_API_KEY", "")
    deployment = os.environ.get("AZURE_OPENAI_EMBEDDING_DEPLOYMENT", "")
    if not (endpoint and api_key and deployment):
        return None
    url = f"{endpoint}/openai/deployments/{deployment}/embeddings?api-version=2024-06-01"
    vectors: list[list[float]] = []
    with httpx.Client(timeout=60, headers={"api-key": api_key}) as client:
        for i in range(0, len(texts), batch_size):
            resp = client.post(url, json={"input": texts[i : i + batch_size]})
            resp.raise_for_status()
            data = sorted(resp.json()["data"], key=lambda item: item["index"])
            vectors.extend(item["embedding"] for item in data)
    return vectors


def build_vectors(
    chunks: list[TextChunk],
    vectors_dir: Path,
    live_embeddings: bool = False,
) -> dict:
    """Compute embeddings for all chunks and write vectors/embeddings.parquet + index.json."""
    vectors_dir.mkdir(parents=True, exist_ok=True)
    texts = [chunk.text for chunk in chunks]
    mode = "local_hash_256"
    vectors: list[list[float]] | None = None
    if live_embeddings and texts:
        vectors = _azure_embeddings(texts)
        if vectors is not None:
            mode = "azure_openai"
    if vectors is None:
        vectors = _local_hash_embeddings(texts, dim=256)

    dim = len(vectors[0]) if vectors else 256
    frame = pd.DataFrame(
        {
            "chunk_id": [c.chunk_id for c in chunks],
            "accession": [c.accession for c in chunks],
            "source_kind": [c.source_kind for c in chunks],
            "vector": vectors,
        }
    )
    frame.to_parquet(vectors_dir / "embeddings.parquet", index=False)
    meta = {
        "mode": mode,
        "dimension": dim,
        "count": len(chunks),
        "created_at": datetime.now(UTC).isoformat(),
    }
    (vectors_dir / "index.json").write_text(json.dumps(meta, indent=2) + "\n", encoding="utf-8")
    return meta


_NUMERIC_FLOAT_COLUMNS = (
    "sample_size_mm",
    "thickness_mm",
    "o2_fraction",
    "pressure_kpa",
    "flow_cm_s",
    "gravity_level_g",
    "outcome_value",
)
_JSON_SERIALIZED_COLUMNS = (
    "sample_dimensions_mm",
    "diluent_fractions",
    "metrics",
    "provenance",
    "notes",
)


def _parquet_safe_frame(frame: pd.DataFrame) -> pd.DataFrame:
    """Serialize nested object/dict/list columns as JSON strings and enforce numeric dtypes."""
    out = frame.copy()
    for col in _NUMERIC_FLOAT_COLUMNS:
        if col in out.columns:
            out[col] = pd.to_numeric(out[col], errors="coerce").astype("float64")
    for col in _JSON_SERIALIZED_COLUMNS:
        if col in out.columns:
            out[col] = (
                out[col]
                .map(lambda v: json.dumps(v) if isinstance(v, dict | list) else v)
                .astype("string")
            )
    for col in out.columns:
        if out[col].dtype == object:
            sample = out[col].dropna()
            if not sample.empty and isinstance(sample.iloc[0], dict | list):
                out[col] = (
                    out[col]
                    .map(lambda v: json.dumps(v) if isinstance(v, dict | list) else v)
                    .astype("string")
                )
            elif sample.empty:
                out[col] = out[col].astype("string")
    return out


def write_snapshot(
    snapshots_dir: Path,
    snapshot_id: str,
    rows: list[ExperimentalTest],
    frame: pd.DataFrame,
    investigations: list[Investigation],
    chunks: list[TextChunk],
    normalize_stats: dict,
    live_embeddings: bool = False,
) -> SnapshotPointer:
    """Write complete snapshot bundle and snapshots/latest.json pointer."""
    target = snapshots_dir / snapshot_id
    target.mkdir(parents=True, exist_ok=True)

    _ = frame
    write_tests_parquet(rows, target / "tests.parquet")

    inv_list = InvestigationList(
        items=investigations,
        total=len(investigations),
        limit=max(1, min(100, len(investigations))),
        offset=0,
    )
    (target / "investigations.json").write_text(
        inv_list.model_dump_json(indent=2) + "\n", encoding="utf-8"
    )

    chunks_lines = "\n".join(chunk.model_dump_json() for chunk in chunks)
    (target / "chunks.jsonl").write_text(
        chunks_lines + ("\n" if chunks_lines else ""), encoding="utf-8"
    )

    vec_meta = build_vectors(chunks, target / "vectors", live_embeddings=live_embeddings)

    now = datetime.now(UTC)
    snapshot_md = "\n".join(
        [
            f"# FireLens Snapshot `{snapshot_id}`",
            "",
            f"- Created (UTC): {now.isoformat()}",
            f"- Investigations: {len(investigations)}",
            f"- Imported source records: {len(rows)}",
            f"- Imported CSV tables: {normalize_stats.get('mapped_tables', 0)}",
            f"- Study-level summary/range tables: {normalize_stats.get('study_level_tables', 0)}",
            f"- Text chunks: {len(chunks)}",
            f"- Embeddings mode: {vec_meta['mode']} (dim={vec_meta['dimension']})",
            "",
            "## Scientific Caveats",
            "- Missing measurements remain null; range/list tables stay at study level.",
            "- No partial-gravity data exists in PSI; no safety recommendations implied.",
        ]
    )
    (target / "SNAPSHOT.md").write_text(snapshot_md + "\n", encoding="utf-8")

    pointer = SnapshotPointer(
        snapshot_id=snapshot_id,
        created_at=now,
        path=f"snapshots/{snapshot_id}/",
        investigation_count=len(investigations),
        test_count=len(rows),
        chunk_count=len(chunks),
        files=[
            "tests.parquet",
            "investigations.json",
            "chunks.jsonl",
            "vectors/embeddings.parquet",
            "vectors/index.json",
            "SNAPSHOT.md",
        ],
    )
    (snapshots_dir / "latest.json").write_text(
        pointer.model_dump_json(indent=2) + "\n", encoding="utf-8"
    )
    return pointer
