"""Tests for Phase 4 CSV normalization and Phase 5 precomputation/snapshot."""

import json
import zipfile

import pandas as pd
import pymupdf
import yaml

from api.config import ROOT
from api.models import InvestigationList, SnapshotPointer, TextChunk
from harvest.maps_schema import ColumnMap
from harvest.normalize import load_column_maps, normalize_all
from harvest.pipeline import run_pipeline


def test_all_22_column_maps_validate():
    maps_dir = ROOT / "harvest/maps"
    maps = load_column_maps(maps_dir)
    assert len(maps) == 22
    assert sum(1 for m in maps if not m.study_level_only) == 11
    assert sum(1 for m in maps if m.study_level_only) == 11
    assert all(m.review_status == "reviewed" for m in maps)


def test_normalize_conversions_non_scalar_cells_and_duplicates(tmp_path):
    raw_dir = tmp_path / "raw"
    acc_dir = raw_dir / "PSI-999"
    acc_dir.mkdir(parents=True)
    maps_dir = tmp_path / "maps"
    maps_dir.mkdir()

    (acc_dir / "manifest.json").write_text(
        json.dumps(
            {
                "accession": "PSI-999",
                "title": "Synthetic Unit Conversion Study",
                "version": "2",
                "doi": "10.0000/test-999",
                "flightProgram": "ISS",
                "objective": "Verify unit conversions. Ensure missing cells stay null.",
            }
        )
    )
    csv_text = (
        "Test,Date,Fuel,O2_pct,P_mmHg,N2,He,Cool,Outcome,BurnTime\n"
        "T1,03/05/2009,Methanol,21.0,760.0,0.79,0,no,Extinction,4.2\n"
        "T1,bad-date,Ethane,30.0,0,0.70,0,yes,Extinction,RAMP\n"
        "T2,,Propane,RAMP,750.0,0.5,0.2,no,Unexpected,3.1\n"
        ",,,,,,,,,\n"
    )
    (acc_dir / "sample.csv").write_bytes(csv_text.encode("cp1252"))

    map_data = {
        "schema_version": 1,
        "accession": "PSI-999",
        "source_file": "sample.csv",
        "encoding": "cp1252",
        "id_column": "Test",
        "default_fuel_phase": "liquid",
        "default_oxygen_basis": "mole",
        "columns": {
            "test_date": {"source_column": "Date", "date_format": "%m/%d/%Y"},
            "fuel": {"source_column": "Fuel"},
            "o2_fraction": {"source_column": "O2_pct", "unit": "percent", "multiplier": 0.01},
            "pressure_kpa": {
                "source_column": "P_mmHg",
                "unit": "mmHg",
                "multiplier": 0.1333223684,
            },
            "outcome": {"source_column": "Outcome"},
        },
        "diluent_columns": {"N2": "N2", "He": "He"},
        "cool_flame_column": "Cool",
        "metrics": {"burn_time": {"source_column": "BurnTime", "unit": "s"}},
        "outcome_map": {"Extinction": "extinguished"},
        "review_status": "reviewed",
    }
    (maps_dir / "PSI-999.yaml").write_text(yaml.safe_dump(map_data))

    rows, frame, stats = normalize_all(raw_dir, maps_dir)
    assert stats["mapped_tables"] == 1
    assert stats["total_rows"] == 3
    assert len(frame) == 3

    r0, r1, r2 = rows
    assert r0.test_id == "T1"
    assert r0.o2_fraction == 0.21
    assert abs(r0.pressure_kpa - 101.325) < 0.01
    assert r0.diluent == "N2"
    assert r0.outcome == "extinguished"
    assert r0.metrics["burn_time"].value == 4.2
    assert r0.source_row == 2

    # Duplicate ID disambiguated; zero pressure & RAMP metric stay null; cool flame wins
    assert r1.test_id == "T1-r3"
    assert r1.test_date is None
    assert r1.pressure_kpa is None
    assert "burn_time" not in r1.metrics
    assert r1.outcome == "cool_flame"
    assert r1.source_row == 3

    # RAMP O2 stays null; unmapped outcome becomes unknown; blank trailing row skipped
    assert r2.o2_fraction is None
    assert r2.outcome == "unknown"
    assert set(r2.diluent.split(" / ")) == {"N2", "He"}


def test_end_to_end_precompute_and_snapshot(tmp_path):
    raw_dir = tmp_path / "raw"
    acc_dir = raw_dir / "PSI-500"
    docs_dir = acc_dir / "documents" / "Reports"
    docs_dir.mkdir(parents=True)
    ctx_dir = raw_dir / "context"
    ctx_dir.mkdir(parents=True)
    maps_dir = tmp_path / "maps"
    maps_dir.mkdir()
    snaps_dir = tmp_path / "snapshots"

    (acc_dir / "manifest.json").write_text(
        json.dumps(
            {
                "accession": "PSI-500",
                "title": "Synthetic Solid Flammability Study",
                "version": "1",
                "doi": "10.0000/psi-500",
                "experimentHardware": "MSG Flow Duct",
                "flightProgram": "ISS",
                "objective": "Measure flame spread over fabric in microgravity.",
                "approach": "Vary oxygen and airflow.",
                "related_glds": "PSI-25, PSI-26",
            }
        )
    )
    (acc_dir / "table.csv").write_text(
        "Id,Fuel,XO2,P_atm,Flow\nA1,PMMA,0.25,1.0,10.0\nA2,PMMA,0.35,0.7,20.0\n"
    )

    # Synthetic PDF document
    pdf_doc = pymupdf.open()
    page = pdf_doc.new_page()
    page.insert_text((72, 72), "BASS microgravity combustion final report page 1.")
    pdf_doc.save(str(docs_dir / "report.pdf"))
    pdf_doc.close()

    # Synthetic DOCX document
    docx_path = docs_dir / "notes.docx"
    with zipfile.ZipFile(docx_path, "w") as zf:
        zf.writestr(
            "word/document.xml",
            '<?xml version="1.0" encoding="UTF-8"?>'
            '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
            "<w:body><w:p><w:r><w:t>Synthetic DOCX summary paragraph.</w:t></w:r></w:p></w:body>"
            "</w:document>",
        )

    # Synthetic context file
    (ctx_dir / "apollo-1.txt").write_text("Apollo 1 fire lessons learned context.")
    (ctx_dir / "apollo-1.source.json").write_text(
        json.dumps(
            {
                "id": "apollo-1",
                "url": "https://www.nasa.gov/history/apollo-1/",
                "text_file": "apollo-1.txt",
                "text_integrity": {"sha256": "a" * 64},
            }
        )
    )

    ColumnMap(
        accession="PSI-500",
        source_file="table.csv",
        id_column="Id",
        default_fuel_phase="solid",
        columns={
            "fuel": {"source_column": "Fuel"},
            "o2_fraction": {"source_column": "XO2", "multiplier": 1.0},
            "pressure_kpa": {"source_column": "P_atm", "unit": "atm", "multiplier": 101.325},
            "flow_cm_s": {"source_column": "Flow", "unit": "cm/s"},
        },
        review_status="reviewed",
    )
    (maps_dir / "PSI-500.yaml").write_text(
        yaml.safe_dump(
            {
                "schema_version": 1,
                "accession": "PSI-500",
                "source_file": "table.csv",
                "id_column": "Id",
                "default_fuel_phase": "solid",
                "columns": {
                    "fuel": {"source_column": "Fuel"},
                    "o2_fraction": {"source_column": "XO2", "multiplier": 1.0},
                    "pressure_kpa": {
                        "source_column": "P_atm",
                        "unit": "atm",
                        "multiplier": 101.325,
                    },
                    "flow_cm_s": {"source_column": "Flow", "unit": "cm/s"},
                },
                "review_status": "reviewed",
            }
        )
    )

    result = run_pipeline(
        stage="all",
        raw_dir=raw_dir,
        maps_dir=maps_dir,
        snapshots_dir=snaps_dir,
        snapshot_id="test-snap",
    )
    pointer = SnapshotPointer.model_validate_json((snaps_dir / "latest.json").read_text())
    assert pointer.snapshot_id == "test-snap"
    assert pointer.investigation_count == 1
    assert pointer.test_count == 2
    assert pointer.chunk_count >= 5  # 2 fields + 1 summary + 1 pdf + 1 docx + 1 context
    assert result["stats"]["total_rows"] == 2

    snap = snaps_dir / "test-snap"
    df = pd.read_parquet(snap / "tests.parquet")
    assert len(df) == 2

    inv_list = InvestigationList.model_validate_json((snap / "investigations.json").read_text())
    inv = inv_list.items[0]
    assert inv.data_status == "normalized"
    assert inv.condition_ranges["oxygen"].minimum == 0.25
    assert inv.condition_ranges["oxygen"].maximum == 0.35
    assert "prevention" in inv.fire_safety_tags

    chunks = [
        TextChunk.model_validate_json(line)
        for line in (snap / "chunks.jsonl").read_text().splitlines()
        if line.strip()
    ]
    assert any(c.source_kind == "document" and c.page == 1 for c in chunks)
    assert any(c.source_kind == "context_page" and c.accession is None for c in chunks)

    emb = pd.read_parquet(snap / "vectors/embeddings.parquet")
    assert len(emb) == len(chunks)
    assert (snap / "SNAPSHOT.md").exists()


def test_real_harvested_raw_normalizes_cleanly_when_present():
    raw_dir = ROOT / "raw/plan-aligned-20261114"
    if not raw_dir.exists():
        return
    rows, frame, stats = normalize_all(raw_dir, ROOT / "harvest/maps")
    assert stats["mapped_tables"] == 11
    assert stats["study_level_tables"] == 11
    assert len(rows) == len(frame)
    assert len(rows) > 1500
    assert (frame["o2_fraction"].dropna().between(0.0, 1.0)).all()
    assert (frame["pressure_kpa"].dropna() > 0.0).all()
