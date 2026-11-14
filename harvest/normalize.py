"""Phase 4: apply reviewed column maps (harvest/maps/PSI-<n>.yaml) to the raw CSVs.

Rules (AGENTS.md): numbers are converted only through harvest/units.yaml; anything that
does not parse cleanly (ranges, lists, '<1', text) stays null with a note, and is never
expanded into invented test runs. Every row keeps its original file, row and hash.
"""

import csv
import io
import json
import re
from dataclasses import dataclass, field
from datetime import date, datetime
from pathlib import Path

import yaml

from api.models import ExperimentalTest, ReviewStatus
from harvest import psi

HARVEST_DIR = Path(__file__).resolve().parent
MAPS_DIR = HARVEST_DIR / "maps"
UNITS_FILE = HARVEST_DIR / "units.yaml"
NUMBER = re.compile(r"^[+-]?(\d+(\.\d*)?|\.\d+)([eE][+-]?\d+)?$")
SIZE = re.compile(r"(\d+(?:\.\d+)?)\s*(cm|mm|micron)\b", re.IGNORECASE)
GEOMETRY_WORDS = [
    ("sphere", "sphere"),
    ("cylinder", "cylinder"),
    ("rod", "rod"),
    ("film", "thin film"),
    ("slab", "slab"),
    ("sheet", "flat sheet"),
    ("flat", "flat sample"),
    ("fabric", "fabric"),
]
TARGET_UNITS = {"o2_fraction", "pressure_kpa", "sample_size_mm", "flow_cm_s"}
# Same bounds as api/models.py; a violating source value is reported, never clipped.
PHYSICAL = {
    "o2_fraction": lambda v: 0 <= v <= 1,
    "pressure_kpa": lambda v: v > 0,
    "sample_size_mm": lambda v: v > 0,
    "flow_cm_s": lambda v: v >= 0,
}


def norm(header: str) -> str:
    """Collapse the irregular whitespace PSI headers carry ('XO2  after test ')."""
    return re.sub(r"\s+", " ", header).strip()


def load_units(path: Path = UNITS_FILE) -> dict[str, dict[str, float]]:
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def load_maps(directory: Path = MAPS_DIR) -> list[dict]:
    return [
        yaml.safe_load(p.read_text(encoding="utf-8")) for p in sorted(directory.glob("PSI-*.yaml"))
    ]


def parse_number(text: str) -> float | None:
    value = text.strip()
    return float(value) if NUMBER.match(value) else None


def convert(value: float, target: str, unit: str, units: dict) -> float:
    try:
        return value * units[target][unit]
    except KeyError as exc:
        raise ValueError(f"No conversion for {target} from {unit!r} in units.yaml") from exc


def parse_date_mdy(text: str) -> date | None:
    """US month/day/year as PSI exports it; FLEX mixes 4- and 2-digit years."""
    for fmt in ("%m/%d/%Y", "%m/%d/%y"):
        try:
            return datetime.strptime(text.strip(), fmt).date()
        except ValueError:
            continue
    return None


def extract_geometry(text: str) -> str | None:
    lowered = text.lower()
    return next((label for word, label in GEOMETRY_WORDS if word in lowered), None)


def extract_size_mm(text: str, units: dict) -> float | None:
    """Only when the text holds exactly one size; 'film 100 micron, 2 cm wide' stays null."""
    matches = SIZE.findall(text)
    if len(matches) != 1:
        return None
    number, unit = matches[0]
    return convert(float(number), "sample_size_mm", unit.lower(), units)


@dataclass
class TableResult:
    accession: str
    file: str
    rows: list[ExperimentalTest] = field(default_factory=list)
    blank_rows: int = 0
    notes: list[str] = field(default_factory=list)


class RowContext:
    def __init__(self, header: list[str], cells: list[str]):
        self.values = {norm(h): (cells[i] if i < len(cells) else "") for i, h in enumerate(header)}

    def get(self, column: str) -> str:
        key = norm(column)
        if key not in self.values:
            raise KeyError(f"Map refers to missing column {column!r}")
        return self.values[key].strip()


def apply_field(name: str, spec: dict, row: RowContext, units: dict, notes: list[str]):
    if "template" in spec:
        return re.sub(r"\{([^}]+)\}", lambda m: row.get(m.group(1)), spec["template"])
    if "compose" in spec:  # e.g. diluent species with non-zero mole fractions
        parts = []
        for label, column in spec["compose"].items():
            number = parse_number(row.get(column))
            if number:
                parts.append(f"{label} {number:g}")
        return "; ".join(parts) or None
    if "rules" in spec:
        label_column = spec.get("keep_label")
        if label_column and row.get(label_column):
            notes.append(f"{norm(label_column)}: {row.get(label_column)}")
        for rule in spec["rules"]:
            if all(
                re.search(pattern, row.get(column), re.IGNORECASE)
                for column, pattern in rule["when"].items()
            ):
                return rule["then"]
        return "unknown"

    text = row.get(spec["source"])
    if not text and "fallback" in spec:
        text = row.get(spec["fallback"])
    if not text:
        return None
    if spec.get("extract") == "geometry":
        return extract_geometry(text)
    if spec.get("extract") == "size":
        size = extract_size_mm(text, units)
        if size is None:
            notes.append(f"{name}: size not parsed from {text!r}")
        return size
    if spec.get("parse") == "date_mdy":
        parsed = parse_date_mdy(text)
        if parsed is None:
            notes.append(f"{name}: unparsed date {text!r}")
        return parsed
    if name in TARGET_UNITS:
        number = parse_number(text)
        if number is None:
            notes.append(f"{name}: non-numeric source value {text!r} left empty")
            return None
        value = convert(number, name, spec["unit"], units)
        if not PHYSICAL[name](value):
            notes.append(f"{name}: source value {text!r} outside physical bounds, left empty")
            return None
        return value
    return spec.get("prefix", "") + text


def normalize_table(
    mapping: dict, table: dict, inventory: dict, units: dict, raw_dir: Path
) -> TableResult:
    accession = mapping["accession"]
    result = TableResult(accession, table["file"])
    content = (raw_dir / accession / table["file"]).read_bytes()
    text, _ = psi.decode_csv(content)
    physical = list(csv.reader(io.StringIO(text)))
    header = physical[0]
    reviewed = mapping.get("review", {}).get("status") == "reviewed"
    provenance_base = {
        "source_url": inventory["page_url"],
        "source_file": table["file"],
        "source_version": inventory["version"],
        "retrieved_at": inventory["retrieved_at"],
        "source_sha256": inventory["sha256"][table["file"]],
    }
    seen: set[str] = set()
    for index, cells in enumerate(physical[1:], start=2):  # header is physical row 1
        if not any(cell.strip() for cell in cells):
            result.blank_rows += 1
            continue
        row = RowContext(header, cells)
        notes: list[str] = []
        record: dict = {**table.get("defaults", {})}
        for name, spec in table["fields"].items():
            record[name] = apply_field(name, spec, row, units, notes)
        metrics = {}
        for metric, spec in (table.get("metrics") or {}).items():
            raw = row.get(spec["source"])
            number = parse_number(raw) if raw else None
            if number is not None:
                metrics[metric] = {"value": number, "unit": spec["unit"]}
            elif raw and raw not in {"-", "none"}:
                notes.append(f"{metric}: non-numeric {raw!r}")
        test_id = record.get("test_id") or f"r{index}"
        if test_id in seen:
            test_id = f"{test_id}@r{index}"
        seen.add(test_id)
        record.update(
            test_id=test_id,
            accession=accession,
            investigation=mapping.get("investigation"),
            doi=inventory.get("doi"),
            metrics=metrics,
            evidence_type="measurement",
            review_status=ReviewStatus.REVIEWED if reviewed else ReviewStatus.UNREVIEWED,
            provenance={**provenance_base, "source_row": index},
            notes=notes,
        )
        result.rows.append(ExperimentalTest.model_validate(record))
    return result


def load_inventory(raw_dir: Path) -> dict[str, dict]:
    """Per accession: version, DOI, page URL, retrieval time and table hashes."""
    report = json.loads((raw_dir / "harvest.json").read_text(encoding="utf-8"))
    inventory = {}
    for item in report["investigations"]:
        manifest = item.get("manifest")
        if not manifest:
            continue
        inventory[item["catalogue"]["accession"]] = {
            "version": manifest["version"],
            "doi": manifest["doi"],
            "page_url": manifest["page_url"],
            "retrieved_at": report["retrieved_at"],
            "sha256": {t["file"]: t["sha256"] for t in item.get("tables", []) if t["success"]},
        }
    return inventory


def normalize_all(raw_dir: Path = Path("raw")) -> list[TableResult]:
    units = load_units()
    inventory = load_inventory(raw_dir)
    results = []
    for mapping in load_maps():
        accession = mapping["accession"]
        if accession not in inventory:
            raise ValueError(f"{accession} has a map but was not harvested")
        for table in mapping["tables"]:
            results.append(normalize_table(mapping, table, inventory[accession], units, raw_dir))
    return results
