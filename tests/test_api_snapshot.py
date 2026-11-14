"""Snapshot-mode API tests on a tiny synthetic snapshot (offline; no NASA, no LLM)."""

import json
import math
import time

import pytest
from fastapi.testclient import TestClient

import api.main
from api.config import load_profiles
from api.models import ExperimentalTest, Investigation, InvestigationList
from api.store import SnapshotStore, StoreManager
from harvest.snapshot import condition_ranges
from harvest.snapshot import tests_frame as frame_of

RETRIEVED = "2026-11-14T00:00:00Z"


def row(accession, test_id, review="reviewed", **values) -> ExperimentalTest:
    return ExperimentalTest.model_validate(
        {
            "test_id": test_id,
            "accession": accession,
            "evidence_type": "measurement",
            "review_status": review,
            "doi": f"10.0/{accession}",
            "provenance": {
                "source_url": f"https://psi.nasa.gov/physci/repo/data/investigations/{accession}",
                "source_file": f"{accession}.csv",
                "source_version": "1",
                "retrieved_at": RETRIEVED,
                "source_row": int(test_id[1:]) + 1,
                "source_sha256": "a" * 64,
            },
            **values,
        }
    )


ROWS = [
    row("PSI-69", "t1", o2_fraction=0.34, pressure_kpa=70.0, fuel_phase="liquid"),
    row("PSI-69", "t2", o2_fraction=0.21, pressure_kpa=101.3, fuel_phase="liquid"),
    row("PSI-69", "t3", o2_fraction=0.30, pressure_kpa=72.0, fuel_phase="liquid"),
    row("PSI-26", "t1", fuel_phase="solid", fuel="PMMA sphere 2 cm"),
    row("PSI-25", "t1", review="unreviewed", o2_fraction=0.20, fuel_phase="solid"),
    row("PSI-25", "t2", review="unreviewed", o2_fraction=0.22, fuel_phase="solid"),
]


def investigation(accession, acronym, phase, tags, publications=()) -> Investigation:
    rows = [r for r in ROWS if r.accession == accession]
    return Investigation(
        accession=accession,
        title=f"{acronym} title",
        acronym=acronym,
        research_area="Combustion Science",
        doi=f"10.0/{accession}",
        version="1",
        source_url=f"https://psi.nasa.gov/physci/repo/data/investigations/{accession}",
        retrieved_at=RETRIEVED,
        fuel_phase=phase,
        fire_safety_tags=tags,
        publications=list(publications),
        condition_ranges=condition_ranges(rows),
        test_count=len(rows),
        data_status="normalized",
    )


def write_snapshot(root, snapshot_id):
    folder = root / snapshot_id
    folder.mkdir(parents=True)
    frame_of(ROWS).to_parquet(folder / "tests.parquet", index=False)
    items = [
        investigation("PSI-25", "BASS-II", "solid", ["prevention"]),
        investigation("PSI-26", "BASS", "solid", ["prevention", "suppression"], ["Paper"]),
        investigation("PSI-69", "FLEX", "liquid", ["suppression"], ["Paper A"]),
    ]
    listing = InvestigationList(items=items, total=3, limit=100, offset=0, mode="snapshot")
    (folder / "investigations.json").write_text(listing.model_dump_json())
    info = {
        "snapshot_id": snapshot_id,
        "created_at": "2026-11-14T01:00:00+00:00",
        "psi_retrieved_at": RETRIEVED.replace("Z", "+00:00"),
        "investigation_count": 3,
        "test_count": len(ROWS),
        "reviewed_test_count": 4,
        "chunk_count": 0,
    }
    (folder / "snapshot.json").write_text(json.dumps(info))
    (root / "latest.json").write_text(json.dumps({"snapshot_id": snapshot_id, "path": snapshot_id}))
    return folder


@pytest.fixture
def client(tmp_path, monkeypatch):
    folder = write_snapshot(tmp_path, "20261114T010000Z")
    monkeypatch.setattr(api.main.DATA, "_store", SnapshotStore(folder))
    monkeypatch.setattr(api.main.settings, "allow_unreviewed", False)
    return TestClient(api.main.app)


def items_by_id(payload):
    return {item["accession"]: item for item in payload["items"]}


def test_rank_formula_is_computed_from_rows(client):
    payload = client.get("/rank?profile=moon_base").json()
    assert payload["mode"] == "snapshot"
    flex = items_by_id(payload)["PSI-69"]
    config = load_profiles()
    # Moon base: O2 >= 0.30 (-0.03 tol), P <= 70 (+15 tol). t1 and t3 inside, t2 outside.
    assert flex["tests_near_profile"] == 2
    c, f, m = 2 / 3, config.fuel_realism["liquid"], 1.0
    d = 0.7 * math.log(4) / math.log(501) + 0.3
    expected = 0.40 * c + 0.25 * f + 0.20 * m + 0.15 * d
    assert flex["score"] == pytest.approx(expected, abs=1e-4)
    assert flex["status"] == "scored"
    assert payload["items"][0]["accession"] == "PSI-69"  # only scored item ranks first
    assert any("partial-gravity" in w for w in payload["warnings"])


def test_missing_conditions_give_null_not_zero(client):
    bass = items_by_id(client.get("/rank?profile=moon_base").json())["PSI-26"]
    assert bass["score"] is None and bass["status"] == "metadata_only"
    assert bass["breakdown"]["condition"] is None
    assert "No tests report O2" in bass["gaps"]


def test_unreviewed_rows_are_excluded_unless_allowed(client, monkeypatch):
    bass2 = items_by_id(client.get("/rank?profile=moon_base").json())["PSI-25"]
    assert bass2["status"] == "metadata_only"
    assert any("not reviewed" in gap for gap in bass2["gaps"])
    assert any("below the profile minimum" in gap for gap in bass2["gaps"])
    monkeypatch.setattr(api.main.settings, "allow_unreviewed", True)
    payload = client.get("/rank?profile=moon_base").json()
    bass2 = items_by_id(payload)["PSI-25"]
    assert bass2["breakdown"]["condition"] == 0  # O2 0.20/0.22 below 0.27: tested, not near
    assert any("not reviewed" in w for w in payload["warnings"])


def test_goal_changes_category_term(client):
    flex = items_by_id(client.get("/rank?profile=moon_base&goal=detection").json())["PSI-69"]
    assert flex["breakdown"]["category"] == 0
    flex = items_by_id(client.get("/rank?profile=moon_base&goal=suppression").json())["PSI-69"]
    assert flex["breakdown"]["category"] == 1


def test_tests_endpoint_filters_with_sql(client):
    assert client.get("/tests").json()["total"] == 6
    high = client.get("/tests?o2_min=0.3").json()
    assert {r["test_id"] for r in high["items"]} == {"t1", "t3"}
    assert client.get("/tests?reviewed_only=true").json()["total"] == 4
    assert client.get("/tests?accession=PSI-26&fuel_phase=solid").json()["total"] == 1
    first = client.get("/tests?accession=PSI-69").json()["items"][0]
    assert first["provenance"]["source_row"] == 2 and first["doi"] == "10.0/PSI-69"


def test_export_csv_cites_and_keeps_missing_values_empty(client):
    text = client.get("/export?accession=PSI-26").text
    lines = text.splitlines()
    assert lines[0].startswith("# Source: NASA Physical Sciences Informatics")
    assert "PSI-26 BASS doi:10.0/PSI-26 v1" in lines[1]
    header = lines[-2].split(",")
    values = dict(zip(header, lines[-1].split(","), strict=False))
    assert values["o2_fraction"] == "" and values["pressure_kpa"] == ""
    assert values["source_row"] == "2"
    assert "unreviewed" not in text  # all PSI-26 rows reviewed


def test_compare_is_field_by_field(client):
    payload = client.get("/compare?ids=PSI-26,PSI-25").json()
    assert "Fuel phase: solid" in payload["same"]
    assert any(d.startswith("Fire-safety category") for d in payload["different"])


def test_meta_reports_snapshot(client):
    meta = client.get("/meta").json()
    assert meta["mode"] == "snapshot" and meta["test_count"] == 6
    assert meta["reviewed_test_count"] == 4


def test_pointer_swap_happens_in_background(tmp_path):
    write_snapshot(tmp_path, "20261114T010000Z")
    manager = StoreManager("snapshot", tmp_path, pointer_check_seconds=0)
    assert manager.store.snapshot_id == "20261114T010000Z"
    write_snapshot(tmp_path, "20261114T020000Z")
    deadline = time.monotonic() + 5
    while manager.store.snapshot_id != "20261114T020000Z" and time.monotonic() < deadline:
        time.sleep(0.05)
    assert manager.store.snapshot_id == "20261114T020000Z"


def test_bad_pointer_keeps_serving(tmp_path):
    write_snapshot(tmp_path, "20261114T010000Z")
    manager = StoreManager("snapshot", tmp_path, pointer_check_seconds=0)
    (tmp_path / "latest.json").write_text(json.dumps({"path": "../elsewhere"}))
    assert manager.store.snapshot_id == "20261114T010000Z"
