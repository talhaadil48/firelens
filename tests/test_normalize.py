"""Offline tests for unit conversion and column-map rules (build-steps 4.4). No network."""

from datetime import date

import pytest

from harvest.normalize import (
    TARGET_UNITS,
    convert,
    extract_size_mm,
    load_maps,
    load_units,
    normalize_table,
    parse_date_mdy,
    parse_number,
)
from harvest.snapshot import fire_safety_tags, split_text

UNITS = load_units()
SHA = "0" * 64


@pytest.mark.parametrize(
    ("target", "unit", "value", "expected"),
    [
        ("pressure_kpa", "mmHg", 760, 101.325),
        ("pressure_kpa", "bar", 1.0133, 101.33),
        ("pressure_kpa", "atm", 1, 101.325),
        ("pressure_kpa", "psi", 14.6959, 101.325),
        ("o2_fraction", "percent", 21, 0.21),
        ("sample_size_mm", "cm", 2, 20),
        ("sample_size_mm", "micron", 100, 0.1),
    ],
)
def test_unit_conversions_come_from_yaml(target, unit, value, expected):
    assert convert(value, target, unit, UNITS) == pytest.approx(expected, rel=1e-3)


def test_unknown_unit_is_an_error_not_a_guess():
    with pytest.raises(ValueError):
        convert(1, "pressure_kpa", "torr-ish", UNITS)


@pytest.mark.parametrize("text", ["1.5 - 5", "21; 26.5; 40", "<1", "approx 3", "", "–"])
def test_ranges_lists_and_text_are_not_numbers(text):
    assert parse_number(text) is None


@pytest.mark.parametrize(("text", "value"), [("0.21", 0.21), (" 757.7 ", 757.7), ("-1", -1.0)])
def test_plain_numbers_parse(text, value):
    assert parse_number(text) == value


def test_dates_accept_two_and_four_digit_years():
    assert parse_date_mdy("3/5/2009") == date(2009, 3, 5)
    assert parse_date_mdy("11/18/11") == date(2011, 11, 18)
    assert parse_date_mdy("day 45") is None


def test_size_only_when_unambiguous():
    assert extract_size_mm("PMMA sphere 2 cm", UNITS) == pytest.approx(20)
    assert extract_size_mm("100 micron PMMA film   2 cm wide", UNITS) is None
    assert extract_size_mm("candle", UNITS) is None


def test_every_map_uses_known_units():
    for mapping in load_maps():
        for table in mapping["tables"]:
            for name, spec in table["fields"].items():
                if name in TARGET_UNITS and "unit" in spec:
                    assert spec["unit"] in UNITS[name], (mapping["accession"], name)
            assert mapping["review"]["status"] in {"draft", "reviewed", "rejected"}


def write_table(tmp_path, text: str) -> None:
    folder = tmp_path / "PSI-1"
    folder.mkdir()
    (folder / "t.csv").write_bytes(text.encode("cp1252"))


MAPPING = {
    "accession": "PSI-1",
    "investigation": "TEST",
    "review": {"status": "draft"},
}
TABLE = {
    "file": "t.csv",
    "defaults": {"fuel_phase": "liquid", "gravity": "microgravity"},
    "fields": {
        "test_id": {"source": "Test #"},
        "o2_fraction": {"source": "O2 %", "unit": "percent"},
        "pressure_kpa": {"source": " p  (mmHg) ", "unit": "mmHg"},
        "flow_cm_s": {"source": "Flow", "unit": "cm/s"},
        "outcome": {
            "rules": [
                {"when": {"End": "^ext"}, "then": "extinguished"},
                {"when": {"End": "^done$"}, "then": "ignited"},
            ],
            "keep_label": "End",
        },
    },
    "metrics": {"burn_time": {"source": "Burn (s)", "unit": "s"}},
}
INVENTORY = {
    "page_url": "https://psi.nasa.gov/physci/repo/data/investigations/PSI-1",
    "version": "3",
    "doi": "10.0000/test",
    "retrieved_at": "2026-11-14T00:00:00Z",
    "sha256": {"t.csv": SHA},
}
CSV = (
    "Test #,O2 %,p   (mmHg),Flow,End,Burn (s)\r\n"
    "1,21,760,5,Extinction,4.2\r\n"
    ",,,,,\r\n"
    "1,1.5 - 5,760,-0.3,done,n/a\r\n"
    "2,150,760,,Disruption,\r\n"
)


def test_normalize_table_keeps_provenance_and_never_invents(tmp_path):
    write_table(tmp_path, CSV)
    result = normalize_table(MAPPING, TABLE, INVENTORY, UNITS, tmp_path)
    assert result.blank_rows == 1
    first, duplicate, impossible = result.rows

    assert first.o2_fraction == pytest.approx(0.21)
    assert first.pressure_kpa == pytest.approx(101.325, rel=1e-4)
    assert first.outcome == "extinguished"
    assert first.metrics["burn_time"].value == 4.2 and first.metrics["burn_time"].unit == "s"
    assert first.provenance.source_row == 2  # physical row; header is row 1
    assert first.provenance.source_version == "3" and first.doi == "10.0000/test"
    assert first.review_status == "unreviewed"  # draft maps never yield reviewed rows

    assert duplicate.test_id == "1@r4"  # repeated ID gets a row suffix, not dropped
    assert duplicate.o2_fraction is None  # range stays empty, not split into runs
    assert duplicate.flow_cm_s is None  # negative flow reported, never clipped
    assert any("outside physical bounds" in note for note in duplicate.notes)
    assert duplicate.outcome == "ignited"

    assert impossible.o2_fraction is None  # 150 % is not a fraction
    assert impossible.outcome == "unknown"
    assert "End: Disruption" in impossible.notes


def test_reviewed_map_marks_rows_reviewed(tmp_path):
    write_table(tmp_path, CSV)
    mapping = {**MAPPING, "review": {"status": "reviewed", "reviewer": "someone"}}
    result = normalize_table(mapping, TABLE, INVENTORY, UNITS, tmp_path)
    assert all(row.review_status == "reviewed" for row in result.rows)


def test_missing_column_in_map_fails_loudly(tmp_path):
    write_table(tmp_path, CSV)
    table = {**TABLE, "fields": {**TABLE["fields"], "fuel": {"source": "No such column"}}}
    with pytest.raises(KeyError):
        normalize_table(MAPPING, table, INVENTORY, UNITS, tmp_path)


def test_chunking_respects_size_and_keeps_text():
    text = "\n".join(f"Paragraph {i}. " + "word " * 100 for i in range(20))
    chunks = split_text(text, size=1000)
    assert all(len(chunk) <= 1000 for chunk in chunks)
    assert "Paragraph 19." in chunks[-1]


def test_keyword_tag_fallback():
    keywords = {"suppression": ["extinguish"], "detection": ["smoke"]}
    assert fire_safety_tags("Flame Extinguishment Experiment", keywords) == ["suppression"]
    assert fire_safety_tags("Laminar flames", keywords) == []
