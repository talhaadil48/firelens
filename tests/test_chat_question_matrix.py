"""End-to-end expectations for the owner's ten source-grounded questions."""

import json
import unicodedata
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from api.config import ROOT, Settings
from api.llm import deterministic_sql_filter
from api.main import app, configure_runtime
from api.snapshot import SnapshotLoader

QUESTIONS = json.loads((Path(__file__).parent / "fixtures/chat_questions.json").read_text())


@pytest.fixture(scope="module")
def source_data():
    if not (ROOT / "snapshots/latest.json").exists():
        pytest.skip("Real local snapshot is optional; no measurements fabricated")
    settings = Settings(
        mode="snapshot",
        llm_provider="offline",
        azure_storage_account_url="",
        chat_rate_limit_per_minute=100,
        _env_file=None,
    )
    configure_runtime(settings)
    loader = SnapshotLoader(settings)
    rows, _ = loader.query_tests(limit=None, offset=0)
    try:
        yield settings, {(r.accession, r.test_id): r for r in rows}
    finally:
        configure_runtime(Settings(mode="mock", _env_file=None))


@pytest.mark.parametrize("case", QUESTIONS, ids=lambda c: c["id"])
def test_owner_questions_have_truthful_answers(case, source_data):
    settings, rows = source_data
    response = TestClient(app).post(
        "/chat", json={k: case[k] for k in ["question", "investigation_ids"]}
    )
    assert response.status_code == 200
    frames = [
        json.loads(block.split("data: ", 1)[1])
        for block in response.text.split("\n\n")
        if block.startswith("event: answer")
    ]
    assert len(frames) == 1
    answer = frames[0]
    text = unicodedata.normalize("NFKC", answer["text"]).lower()
    cited = []
    for c in answer["citations"]:
        if not c["id"].startswith("row:"):
            continue
        _, acc, tid = c["id"].split(":", 2)
        row = rows[acc, tid]
        cited.append(row)
        assert c["provenance"] == row.provenance.model_dump(mode="json")
    key = case["id"]
    if key in {"A1", "A3", "B1", "B2", "D1"}:
        assert answer["status"] == "insufficient_evidence"
        assert not cited
        if key == "A1":
            assert "flex" in text and "methanol" in text and "no individual test rows match" in text
        if key == "A3":
            assert "same-r" in text and "oxygen" in text and "pressure" in text
        if key == "B1":
            assert "equipment settings" in text and "calibration" in text
        if key == "B2":
            assert "airflow" in text and "unavailable" in text
        if key == "D1":
            assert "cannot verify" in text and "never" in text
    else:
        assert answer["status"] == "supported" and answer["citations"]
        if key == "A2":
            assert len(cited) >= 2
            assert all(r.o2_fraction > 0.30 and r.pressure_kpa < 105 for r in cited)
            total = sum(
                r.o2_fraction is not None
                and r.o2_fraction > 0.30
                and r.pressure_kpa is not None
                and r.pressure_kpa < 105
                and r.record_kind == "individual_test"
                for r in rows.values()
            )
            assert f"{total} individual source rows" in text
            assert "not the complete result list" in text
        if key == "A4":
            assert len(cited) >= 2 and all(
                r.o2_fraction is not None and r.pressure_kpa is not None for r in cited
            )
            assert any(r.accession == "PSI-159" for r in cited)
            assert "psi-107" in text and "no exact numeric" in text
        if key == "C1":
            assert (
                "cool" in text
                and ("extinguish" in text or "extinction" in text)
                and "..." not in text
            )
        if key == "C2":
            assert (
                "hypothesis" in text
                and "not an established universal result" in text
                and "normal gravity" in text
            )
        if key == "C3":
            assert "identity correction" in text and "psi-10" in text and "cfi-g" in text


@pytest.mark.parametrize(
    "question,lo,hi,exclusive",
    [
        ("oxygen concentrations above 30% and pressures below 105 kPa", 0.30, 105, True),
        ("oxygen above 30 percent and below 105 kPa", 0.30, 105, True),
        ("O2 >= 30% and pressure <= 105 kPa", 0.30, 105, False),
    ],
)
def test_numeric_wording_and_strictness(question, lo, hi, exclusive):
    f = deterministic_sql_filter(question)
    assert f.o2_min == lo and f.pressure_max == hi
    assert ("o2_min" in f.exclusive) == exclusive
    assert ("pressure_max" in f.exclusive) == exclusive


def test_union_fuel_filters_do_not_collapse_to_first_fuel():
    f = deterministic_sql_filter("Compare cotton and PMMA test runs in PSI-25")
    assert set(f.fuels) == {"cotton", "pmma"} and f.fuel is None
    g = deterministic_sql_filter("PSI-159 and PSI-107 ethylene or gaseous flame experiments")
    assert g.fuels == ["ethylene"] and g.fuel_or_phase and g.fuel_phase == "gas"


def test_sql_enforces_strict_bounds_and_fuel_union_on_synthetic_rows(tmp_path, monkeypatch):
    from datetime import UTC, datetime
    from types import SimpleNamespace

    from api.models import ExperimentalTest, Provenance
    from api.snapshot import write_tests_parquet

    values = [
        ("a", "Cotton", 0.30, 100, "solid"),
        ("b", "PMMA", 0.31, 105, "solid"),
        ("c", "PMMA", 0.31, 104, "solid"),
        ("d", "Cotton", 0.40, 104, "solid"),
        ("e", "Methanol", 0.40, 100, "liquid"),
        ("f", "Ethane", 0.40, 100, "gas"),
    ]
    rows = [
        ExperimentalTest(
            accession="PSI-999",
            test_id=tid,
            fuel=fuel,
            fuel_phase=phase,
            o2_fraction=o2,
            pressure_kpa=p,
            evidence_type="measurement",
            provenance=Provenance(
                source_url="https://example.org/synthetic.csv",
                source_file="synthetic.csv",
                source_version="test",
                source_row=i + 2,
                retrieved_at=datetime(2026, 1, 1, tzinfo=UTC),
            ),
        )
        for i, (tid, fuel, o2, p, phase) in enumerate(values)
    ]
    path = tmp_path / "tests.parquet"
    write_tests_parquet(rows, path)
    loader = SnapshotLoader(Settings(llm_provider="offline", _env_file=None))
    monkeypatch.setattr(
        loader,
        "get_snapshot",
        lambda: SimpleNamespace(parquet_path=path, snapshot_date=datetime(2026, 1, 1, tzinfo=UTC)),
    )
    f = deterministic_sql_filter(
        "cotton and PMMA tests with oxygen concentrations above 30% and pressures below 105 kPa"
    )
    assert {r.test_id for r in loader.query_tests_by_sql_filter(f, all_matches=True)} == {"c", "d"}
    inclusive = deterministic_sql_filter(
        "cotton and PMMA tests with O2 >= 30% and pressure <= 105 kPa"
    )
    assert {r.test_id for r in loader.query_tests_by_sql_filter(inclusive)} == {"a", "b", "c", "d"}
    union = deterministic_sql_filter("ethylene or gaseous tests")
    assert {r.test_id for r in loader.query_tests_by_sql_filter(union)} == {"f"}


def test_solid_and_gas_material_filters_cover_kapton_teflon_and_ethane():
    kapton_teflon = deterministic_sql_filter(
        "What airflow velocities were measured for Kapton or Teflon test runs in PSI-101?"
    )
    assert set(kapton_teflon.fuels) == {"kapton", "teflon"}
    assert kapton_teflon.fuel is None
    assert kapton_teflon.fuel_phase == "solid"

    ethane = deterministic_sql_filter("Which ethane flame tests ran below 90 kPa in PSI-159?")
    assert ethane.fuels == ["ethane"]
    assert ethane.fuel_phase == "gas"


def test_document_answer_skips_glossary_and_plot_axis_noise():
    from datetime import UTC, datetime
    from types import SimpleNamespace

    from api.answers import document_answer
    from api.models import TextChunk
    from api.rag import build_citations

    now = datetime(2026, 1, 1, tzinfo=UTC)
    inv = SimpleNamespace(
        accession="PSI-10",
        acronym="ACME/Flame Design",
        doi="10.60555/test-doi",
        version="1",
        retrieved_at=now,
    )
    snap = SimpleNamespace(investigations_by_id={"PSI-10": inv}, snapshot_date=now)
    glossary = TextChunk(
        chunk_id="PSI-10:doc:glossary:p29",
        accession="PSI-10",
        source_kind="document",
        source_file="report.pdf",
        page=29,
        source_url="https://psi.nasa.gov/test",
        text=(
            "Appendix A. Abbreviations and Acronyms\n"
            "HiBMs\nHigh Bit-depth Multi-spectral camera\n"
            "IPSU\nImage Processing and Storage Unit\n"
            "LCTF\nLiquid Crystal Tunable Filter\n"
            "MDCA\nMulti-user Droplet Combustion Apparatus\n"
            "MSG\nMicrogravity Science Glovebox\n"
            "PMT\nPhotomultiplier Tube\n"
            "SOFBALL\nStructure Of Flame Balls At Low Lewis-number"
        ),
    )
    science = TextChunk(
        chunk_id="PSI-10:doc:science:p18",
        accession="PSI-10",
        source_kind="document",
        source_file="report.pdf",
        page=18,
        source_url="https://psi.nasa.gov/test",
        text=(
            "The primary Flame Design objectives quantify soot inception limits and radiative "
            "extinction in spherical diffusion flames. "
            "1.0 0.8 0.6 0.4 0.2 0.0 "
            "Experiments showed soot luminosity varied strongly with dilution and flow velocity."
        ),
    )
    result = document_answer(
        "What were the main science objectives and soot findings of Flame Design?",
        [glossary, science],
        snap,
        build_citations,
    )
    assert result is not None
    assert "Abbreviations and Acronyms" not in result.text
    assert "HiBMs" not in result.text
    assert "1.0 0.8 0.6 0.4 0.2 0.0" not in result.text
    assert "soot inception limits" in result.text
    assert [c.accession for c in result.citations] == ["PSI-10"]
