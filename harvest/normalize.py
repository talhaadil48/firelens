"""Phase 4 CSV normalization into canonical ExperimentalTest rows and validated DataFrames."""

import csv
import hashlib
import io
import json
import math
import re
from datetime import UTC, date, datetime
from pathlib import Path

import pandas as pd
import yaml

from api.models import EvidenceType, ExperimentalTest, Metric, Provenance, SourceCell
from harvest.maps_schema import ColumnMap
from harvest.validation import validate_tests

MISSING_TOKENS = frozenset(
    {"", "-", "–", "—", "n/a", "na", "none", "null", "ramp", "ramped", "tbd"}
)
UNIT_SUFFIX_RE = re.compile(r"\s*(?:atm|cm/s|mm|kpa|bar|mmhg|%|W|s)\s*$", re.IGNORECASE)


def load_column_maps(maps_dir: Path) -> list[ColumnMap]:
    """Load and validate all YAML column maps in maps_dir, excluding TEMPLATE.yaml."""
    maps: list[ColumnMap] = []
    for path in sorted(maps_dir.glob("*.yaml")):
        if path.name == "TEMPLATE.yaml":
            continue
        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
        maps.append(ColumnMap.model_validate(raw))
    return maps


def _parse_numeric(
    raw_value: str | None,
    multiplier: float | None = None,
    offset: float = 0.0,
) -> tuple[float | None, str | None]:
    """Parse a scalar numeric cell, returning (value, note) without fabricating ranges."""
    text = (raw_value or "").strip()
    if text.lower() in MISSING_TOKENS:
        note = f"Non-scalar or missing token '{text}' left null" if text else None
        return None, note
    cleaned = UNIT_SUFFIX_RE.sub("", text).strip()
    try:
        parsed = float(cleaned)
    except ValueError:
        return None, f"Unparseable numeric cell '{text}' left null"
    if not math.isfinite(parsed):
        return None, f"Non-finite numeric cell '{text}' left null"
    scale = multiplier if multiplier is not None else 1.0
    return parsed * scale + offset, None


def _parse_date(raw_value: str | None, date_format: str | None) -> tuple[date | None, str | None]:
    text = (raw_value or "").strip()
    if not text or text.lower() in MISSING_TOKENS:
        return None, None
    fmt = date_format or "%Y-%m-%d"
    try:
        return datetime.strptime(text, fmt).date(), None
    except ValueError:
        return None, f"Unparseable date '{text}' (expected {fmt}) left null"


def _cell(row: list[str], header_index: dict[str, int], column_name: str | None) -> str:
    if not column_name:
        return ""
    idx = header_index.get(column_name)
    if idx is None:
        stripped_map = {k.strip(): v for k, v in header_index.items()}
        idx = stripped_map.get(column_name.strip())
    if idx is None or idx >= len(row):
        return ""
    return row[idx]


def _resolve_test_id(
    raw_row: list[str],
    header_index: dict[str, int],
    column_map: ColumnMap,
    source_row: int,
    seen_ids: set[str],
) -> tuple[str, list[str]]:
    notes: list[str] = []
    raw_id = _cell(raw_row, header_index, column_map.id_column).strip()
    if raw_id:
        candidate = f"{column_map.id_prefix}{raw_id}"
    else:
        candidate = f"{column_map.id_prefix}row-{source_row}"
    if candidate in seen_ids:
        disambiguated = f"{candidate}-r{source_row}"
        notes.append(f"Disambiguated duplicate source test_id '{candidate}' as '{disambiguated}'")
        candidate = disambiguated
    seen_ids.add(candidate)
    return candidate, notes


def _parse_bounded_field(
    field_name: str,
    raw_val: str,
    multiplier: float | None,
    offset: float,
    notes: list[str],
) -> float | None:
    value, parse_note = _parse_numeric(raw_val, multiplier=multiplier, offset=offset)
    if parse_note:
        notes.append(f"{field_name}: {parse_note}")
        return None
    if value is None:
        return None
    if field_name == "o2_fraction" and not (0.0 <= value <= 1.0):
        notes.append(f"o2_fraction out of [0, 1] ({value}) left null")
        return None
    if field_name in {"pressure_kpa", "sample_size_mm"} and value <= 0.0:
        notes.append(f"{field_name} non-positive ({value}) left null")
        return None
    if field_name == "flow_cm_s" and value < 0.0:
        notes.append(f"flow_cm_s negative ({value}) left null")
        return None
    return value


def _parse_diluents(
    raw_row: list[str],
    header_index: dict[str, int],
    column_map: ColumnMap,
    notes: list[str],
) -> tuple[str | None, dict[str, float]]:
    fractions: dict[str, float] = {}
    for gas, col_name in column_map.diluent_columns.items():
        val, note = _parse_numeric(_cell(raw_row, header_index, col_name))
        if note:
            notes.append(f"diluent[{gas}]: {note}")
            continue
        if val is None:
            continue
        if not (0.0 <= val <= 1.0):
            notes.append(f"diluent[{gas}] out of [0, 1] ({val}) ignored")
            return None, {}
        fractions[gas] = val
    if sum(fractions.values()) > 1.0 + 1e-9:
        notes.append("Diluent fractions exceed 1.0; left empty")
        return None, {}
    nonzero = [gas for gas, val in fractions.items() if val > 0.0]
    label = " / ".join(nonzero) if nonzero else None
    return label, fractions


def _resolve_outcome(
    raw_row: list[str],
    header_index: dict[str, int],
    column_map: ColumnMap,
    notes: list[str],
) -> str | None:
    if column_map.cool_flame_column:
        cool_val = _cell(raw_row, header_index, column_map.cool_flame_column).strip()
        if cool_val.lower().startswith("yes"):
            return "cool_flame"
    outcome_spec = column_map.columns.get("outcome")
    if not outcome_spec:
        return None
    raw_outcome = _cell(raw_row, header_index, outcome_spec.source_column).strip()
    if not raw_outcome:
        return None
    if raw_outcome in column_map.outcome_map:
        return column_map.outcome_map[raw_outcome]
    notes.append(f"Unmapped outcome '{raw_outcome}' recorded as unknown")
    return "unknown"


def normalize_csv(
    raw_dir: Path,
    column_map: ColumnMap,
    manifest_info: dict,
    seen_ids: set[str] | None = None,
) -> list[ExperimentalTest]:
    """Normalize one raw CSV file into ExperimentalTest records according to column_map."""
    csv_path = raw_dir / column_map.accession / column_map.source_file
    if not csv_path.exists():
        raise FileNotFoundError(f"Missing CSV file for {column_map.accession}: {csv_path}")

    source_bytes = csv_path.read_bytes()
    reader = csv.reader(io.StringIO(source_bytes.decode(column_map.encoding), newline=""))
    for _ in range(column_map.header_row - 1):
        next(reader, None)
    headers = next(reader, None)
    if not headers:
        return []
    header_index = {name: idx for idx, name in enumerate(headers)}

    tracker = seen_ids if seen_ids is not None else set()
    skip_rows = set(column_map.skip_rows)
    source_url = manifest_info.get(
        "source_url",
        f"https://psi.nasa.gov/physci/repo/data/investigations/{column_map.accession}",
    )
    source_version = str(manifest_info.get("version") or "1")
    retrieved_at = manifest_info.get("retrieved_at") or datetime.now(UTC)
    file_sha256 = hashlib.sha256(source_bytes).hexdigest()
    expected_hash = manifest_info.get("file_hashes", {}).get(column_map.source_file)
    if expected_hash and expected_hash != file_sha256:
        raise ValueError(f"Source hash mismatch: {column_map.accession}/{column_map.source_file}")

    tests: list[ExperimentalTest] = []
    while True:
        source_row = reader.line_num + 1
        raw_row = next(reader, None)
        if raw_row is None:
            break
        if not any(cell.strip() for cell in raw_row):
            continue

        notes: list[str] = []
        record_kind = "source_note" if source_row in skip_rows else column_map.record_kind
        if any(
            "visualization" in cell.casefold() or "visualisation" in cell.casefold()
            for cell in raw_row
        ):
            record_kind = "source_note"
        if record_kind != "individual_test":
            notes.append(
                f"Source record type: {record_kind}; not an independent experimental test."
            )
        test_id, id_notes = _resolve_test_id(raw_row, header_index, column_map, source_row, tracker)
        notes.extend(id_notes)

        test_date: date | None = None
        if "test_date" in column_map.columns:
            spec = column_map.columns["test_date"]
            test_date, date_note = _parse_date(
                _cell(raw_row, header_index, spec.source_column), spec.date_format
            )
            if date_note:
                notes.append(date_note)

        fuel = column_map.default_fuel
        if "fuel" in column_map.columns:
            val = _cell(raw_row, header_index, column_map.columns["fuel"].source_column).strip()
            if val:
                fuel = val

        sample_geometry = column_map.default_sample_geometry
        if "sample_geometry" in column_map.columns:
            val = _cell(
                raw_row, header_index, column_map.columns["sample_geometry"].source_column
            ).strip()
            if val:
                sample_geometry = val

        numeric_values: dict[str, float | None] = {}
        for field_name in ("sample_size_mm", "o2_fraction", "pressure_kpa", "flow_cm_s"):
            spec = column_map.columns.get(field_name)
            if not spec:
                numeric_values[field_name] = None
                continue
            raw_cell = _cell(raw_row, header_index, spec.source_column)
            numeric_values[field_name] = _parse_bounded_field(
                field_name, raw_cell, spec.multiplier, spec.offset, notes
            )

        diluent_label, diluent_fractions = _parse_diluents(raw_row, header_index, column_map, notes)
        outcome = _resolve_outcome(raw_row, header_index, column_map, notes)

        metrics: dict[str, Metric] = {}
        for metric_name, metric_spec in column_map.metrics.items():
            raw_cell = _cell(raw_row, header_index, metric_spec.source_column)
            m_val, m_note = _parse_numeric(raw_cell, multiplier=metric_spec.multiplier)
            if m_note:
                notes.append(f"metric[{metric_name}]: {m_note}")
                continue
            if m_val is not None:
                metrics[metric_name] = Metric(
                    value=m_val,
                    unit=metric_spec.unit,
                    source_column=metric_spec.source_column,
                )

        provenance = Provenance(
            source_url=source_url,
            source_file=column_map.source_file,
            source_version=source_version,
            retrieved_at=retrieved_at,
            source_row=source_row,
            source_sha256=file_sha256,
            is_mock=False,
        )
        tests.append(
            ExperimentalTest(
                accession=column_map.accession,
                investigation=manifest_info.get("title"),
                test_id=test_id,
                record_kind=record_kind,
                source_cells=[
                    SourceCell(
                        column=headers[index]
                        if index < len(headers)
                        else f"Extra column {index + 1}",
                        value=value,
                        column_index=index + 1,
                    )
                    for index, value in enumerate(raw_row)
                ],
                test_date=test_date,
                fuel=fuel,
                fuel_phase=column_map.default_fuel_phase,
                sample_geometry=sample_geometry,
                sample_size_mm=numeric_values["sample_size_mm"],
                o2_fraction=numeric_values["o2_fraction"],
                oxygen_basis=column_map.default_oxygen_basis,
                pressure_kpa=numeric_values["pressure_kpa"],
                diluent=diluent_label,
                diluent_fractions=diluent_fractions,
                flow_cm_s=numeric_values["flow_cm_s"],
                gravity=column_map.default_gravity,
                platform=manifest_info.get("platform"),
                outcome=outcome,
                metrics=metrics,
                source_file=column_map.source_file,
                source_row=source_row,
                doi=manifest_info.get("doi"),
                evidence_type=EvidenceType.MEASUREMENT,
                provenance=provenance,
                notes=notes,
            )
        )
    return tests


def _collect_manifest_info(raw_dir: Path) -> dict[str, dict]:
    """Gather version, DOI, retrieved_at, and CSV SHA-256 hashes per accession."""
    info_by_acc: dict[str, dict] = {}
    report_path = raw_dir / "report.json"
    if report_path.exists():
        report = json.loads(report_path.read_text(encoding="utf-8"))
        default_ts = report.get("started_at")
        for item in report.get("investigations", []):
            acc = item["accession"]
            file_hashes: dict[str, str] = {}
            retrieved_at = default_ts
            for entry in item.get("files", []):
                receipt = entry.get("receipt") or {}
                if entry.get("role") == "table" and receipt.get("sha256"):
                    fname = Path(entry["path"]).name
                    file_hashes[fname] = receipt["sha256"]
                    retrieved_at = receipt.get("retrieved_at") or retrieved_at
            info_by_acc[acc] = {
                "accession": acc,
                "title": item.get("title"),
                "version": str(item.get("version") or "1"),
                "doi": item.get("doi"),
                "retrieved_at": retrieved_at,
                "source_url": f"https://psi.nasa.gov/physci/repo/data/investigations/{acc}",
                "file_hashes": file_hashes,
            }

    for manifest_path in sorted(raw_dir.glob("PSI-*/manifest.json")):
        acc = manifest_path.parent.name
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        entry = info_by_acc.setdefault(
            acc,
            {
                "accession": acc,
                "source_url": f"https://psi.nasa.gov/physci/repo/data/investigations/{acc}",
                "file_hashes": {},
            },
        )
        entry.setdefault("title", manifest.get("title"))
        entry.setdefault("version", str(manifest.get("version") or "1"))
        entry.setdefault("doi", manifest.get("doi"))
        entry["platform"] = manifest.get("flightProgram") or None
        if not entry.get("retrieved_at"):
            entry["retrieved_at"] = datetime.now(UTC).isoformat()
    return info_by_acc


def normalize_all(
    raw_dir: Path, maps_dir: Path
) -> tuple[list[ExperimentalTest], pd.DataFrame, dict]:
    """Normalize all mapped CSVs under raw_dir and validate with Pandera."""
    maps = load_column_maps(maps_dir)
    mapped_sources = {(item.accession, item.source_file) for item in maps}
    for csv_path in sorted(raw_dir.glob("PSI-*/*.csv")):
        key = (csv_path.parent.name, csv_path.name)
        if key not in mapped_sources:
            try:
                csv_path.read_bytes().decode("utf-8-sig")
                encoding = "utf-8-sig"
            except UnicodeDecodeError:
                encoding = "cp1252"
            maps.append(
                ColumnMap(
                    accession=key[0],
                    source_file=key[1],
                    encoding=encoding,
                    record_kind="grouped_summary",
                    notes=["No scalar mapping configured; all original source cells retained."],
                )
            )
    manifest_info = _collect_manifest_info(raw_dir)
    seen_ids_by_acc: dict[str, set[str]] = {}
    all_rows: list[ExperimentalTest] = []
    by_accession: dict[str, int] = {}
    mapped_tables = 0
    study_level_tables = 0

    for cmap in maps:
        if cmap.record_kind != "individual_test":
            study_level_tables += 1
        csv_path = raw_dir / cmap.accession / cmap.source_file
        if not csv_path.exists():
            continue
        mapped_tables += 1
        seen = seen_ids_by_acc.setdefault(cmap.accession, set())
        rows = normalize_csv(
            raw_dir,
            cmap,
            manifest_info.get(cmap.accession, {"accession": cmap.accession}),
            seen_ids=seen,
        )
        all_rows.extend(rows)
        by_accession[cmap.accession] = by_accession.get(cmap.accession, 0) + len(rows)

    frame = validate_tests(all_rows)
    stats = {
        "mapped_tables": mapped_tables,
        "study_level_tables": study_level_tables,
        "total_rows": len(all_rows),
        "by_accession": by_accession,
    }
    return all_rows, frame, stats
