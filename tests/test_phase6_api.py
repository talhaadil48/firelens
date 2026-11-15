"""Comprehensive Phase 6 tests for settings, LLM wrapper, DuckDB snapshot, ranking, and RAG."""

from __future__ import annotations

import csv
import io
import json
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from api.config import Settings
from api.llm import LLMClient, cosine_similarity, deterministic_embed
from api.main import app, configure_runtime
from api.models import (
    AnswerEvent,
    CompareResponse,
    ConditionRange,
    DoneEvent,
    EvidenceType,
    ExperimentalTest,
    ExportResponse,
    Gravity,
    Investigation,
    InvestigationList,
    InvestigationSummary,
    MetaResponse,
    Metric,
    ProgressEvent,
    Provenance,
    Publication,
    RankResponse,
    SnapshotPointer,
    SourceDocument,
    TextChunk,
)
from api.models import (
    TestList as ExperimentListContract,
)
from api.snapshot import SnapshotLoader, write_tests_parquet


def _provenance(
    source_file: str,
    source_row: int | None = 2,
    *,
    page: int | None = None,
    is_mock: bool = False,
) -> Provenance:
    return Provenance(
        source_url="https://psi.nasa.gov/physci/repo/data/investigations/PSI-25",
        source_file=source_file,
        source_version="4",
        retrieved_at=datetime(2026, 11, 14, 12, 0, tzinfo=UTC),
        source_row=source_row,
        page=page,
        is_mock=is_mock,
    )


def _build_synthetic_snapshot(
    root_dir: Path,
    *,
    snapshot_id: str = "20261115T010000Z",
    include_extra_test: bool = False,
) -> Path:
    snap_dir = root_dir / snapshot_id
    snap_dir.mkdir(parents=True, exist_ok=True)
    now = datetime(2026, 11, 14, 15, 0, tzinfo=UTC)

    investigations = [
        Investigation(
            accession="PSI-25",
            title="Burning and Suppression of Solids - II",
            acronym="BASS-II",
            research_area="Combustion Science",
            objectives="Examine solid fabric flame spread and extinction in microgravity.",
            doi="10.60555/bass2-doi",
            version="4",
            source_url="https://psi.nasa.gov/physci/repo/data/investigations/PSI-25",
            retrieved_at=now,
            hardware=["Microgravity Science Glovebox"],
            platform="International Space Station (ISS)",
            fuel_phase="solid",
            fire_safety_tags=["prevention", "suppression"],
            condition_ranges={
                "oxygen": ConditionRange(minimum=0.21, maximum=0.35, unit="fraction"),
                "pressure": ConditionRange(minimum=65.0, maximum=101.3, unit="kPa"),
                "flow": ConditionRange(minimum=5.0, maximum=25.0, unit="cm/s"),
            },
            documents=[
                SourceDocument(
                    name="BASS-II_FinalReport.pdf",
                    url="https://psi.nasa.gov/files/BASS-II_FinalReport.pdf",
                    size_bytes=512000,
                )
            ],
            publications=[Publication(title="BASS-II Solid Flammability", doi="10.1016/bass2")],
            summary=InvestigationSummary(
                objective="Measure cotton and Nomex flame spread across O2 and airflow.",
                fuels_and_geometry="75% cotton / 25% fiberglass and Nomex fabric sheets.",
                conditions_tested="21% to 35% O2, 65 to 101.3 kPa, 5 to 25 cm/s airflow.",
                varied="Oxygen concentration, pressure, and opposed/concurrent flow velocity.",
                sensors=["radiometer", "thermocouple"],
            ),
            test_count=3,
            data_status="normalized",
            fixture=False,
        ),
        Investigation(
            accession="PSI-69",
            title="Flame Extinguishment Experiment",
            acronym="FLEX",
            research_area="Combustion Science",
            objectives="Study isolated liquid heptane droplet combustion and cool flames.",
            doi="10.60555/flex-doi",
            version="3",
            source_url="https://psi.nasa.gov/physci/repo/data/investigations/PSI-69",
            retrieved_at=now,
            hardware=["Multi-user Droplet Combustion Apparatus"],
            platform="International Space Station (ISS)",
            fuel_phase="liquid",
            fire_safety_tags=["suppression"],
            condition_ranges={
                "oxygen": ConditionRange(minimum=0.18, maximum=0.21, unit="fraction"),
                "pressure": ConditionRange(minimum=101.3, maximum=101.3, unit="kPa"),
            },
            documents=[
                SourceDocument(
                    name="FLEX_FinalReport.pdf",
                    url="https://psi.nasa.gov/files/FLEX_FinalReport.pdf",
                    size_bytes=420000,
                )
            ],
            summary=InvestigationSummary(
                objective="Investigate droplet extinction and dual-stage cool flames.",
                fuels_and_geometry="Heptane and methanol spherical droplets.",
                conditions_tested="18% to 21% O2 at 101.3 kPa with N2 and He diluents.",
            ),
            test_count=2,
            data_status="normalized",
            fixture=False,
        ),
        Investigation(
            accession="PSI-100",
            title="Spacecraft Fire Experiment - III",
            acronym="SAFFIRE-III",
            research_area="Combustion Science",
            objectives="Large-scale spacecraft material flame spread test.",
            doi="10.60555/saffire3-doi",
            version="1",
            source_url="https://psi.nasa.gov/physci/repo/data/investigations/PSI-100",
            retrieved_at=now,
            hardware=["Saffire Flow Unit"],
            platform="Cygnus Spacecraft",
            fuel_phase="solid",
            fire_safety_tags=["detection"],
            test_count=0,
            data_status="metadata_only",
            fixture=False,
        ),
        Investigation(
            accession="PSI-999",
            title="Simulated Synthetic Placeholder Study",
            acronym="SIM",
            research_area="Combustion Science",
            objectives="Verify simulated and mock rows are excluded from quantitative scoring.",
            doi=None,
            version="1",
            source_url="https://psi.nasa.gov/physci/repo/data/investigations/PSI-999",
            retrieved_at=now,
            hardware=["Microgravity Science Glovebox"],
            platform="International Space Station (ISS)",
            fuel_phase="solid",
            fire_safety_tags=["prevention"],
            test_count=2,
            data_status="normalized",
            fixture=False,
        ),
    ]

    (snap_dir / "investigations.json").write_text(
        InvestigationList(
            items=investigations, total=len(investigations), limit=100, offset=0
        ).model_dump_json(indent=2),
        encoding="utf-8",
    )

    tests = [
        ExperimentalTest(
            accession="PSI-25",
            investigation="BASS-II",
            test_id="BASS2-01",
            fuel="Cotton-fiberglass blend",
            fuel_phase="solid",
            sample_geometry="flat sheet",
            o2_fraction=0.34,
            pressure_kpa=70.0,
            flow_cm_s=10.0,
            flow_direction="opposed",
            gravity=Gravity.MICROGRAVITY,
            outcome="ignited",
            metrics={"spread_rate": Metric(value=1.8, unit="cm/s")},
            doi="10.60555/bass2-doi",
            evidence_type=EvidenceType.MEASUREMENT,
            provenance=_provenance("bass2_tests.csv", 2),
        ),
        ExperimentalTest(
            accession="PSI-25",
            investigation="BASS-II",
            test_id="BASS2-02",
            fuel="Nomex fabric",
            fuel_phase="solid",
            sample_geometry="flat sheet",
            o2_fraction=0.35,
            pressure_kpa=68.0,
            flow_cm_s=12.0,
            flow_direction="concurrent",
            gravity=Gravity.MICROGRAVITY,
            outcome="ignited",
            metrics={"burn_time": Metric(value=42.0, unit="s")},
            doi="10.60555/bass2-doi",
            evidence_type=EvidenceType.MEASUREMENT,
            provenance=_provenance("bass2_tests.csv", 3),
        ),
        ExperimentalTest(
            accession="PSI-25",
            investigation="BASS-II",
            test_id="BASS2-03",
            fuel="Cotton-fiberglass blend",
            fuel_phase="solid",
            o2_fraction=0.21,
            pressure_kpa=101.3,
            flow_cm_s=None,  # Intentionally null to test CSV empty-string export & flow filtering
            gravity=Gravity.MICROGRAVITY,
            outcome="extinguished",
            doi="10.60555/bass2-doi",
            evidence_type=EvidenceType.MEASUREMENT,
            provenance=_provenance("bass2_tests.csv", 4),
        ),
        ExperimentalTest(
            accession="PSI-25",
            investigation="BASS-II",
            test_id="BASS2-GROUP",
            record_kind="grouped_summary",
            fuel="PMMA",
            fuel_phase="solid",
            o2_fraction=0.99,
            pressure_kpa=30.0,
            gravity=Gravity.MICROGRAVITY,
            outcome="ignited",
            doi="10.60555/bass2-doi",
            evidence_type=EvidenceType.MEASUREMENT,
            provenance=_provenance("bass2_tests.csv", 5),
        ),
        ExperimentalTest(
            accession="PSI-69",
            investigation="FLEX",
            test_id="FLEX-01",
            fuel="n-heptane",
            fuel_phase="liquid",
            sample_geometry="droplet",
            sample_size_mm=3.2,
            o2_fraction=0.21,
            pressure_kpa=101.3,
            diluent="He",
            diluent_fractions={"He": 0.79},
            flow_cm_s=0.0,
            gravity=Gravity.MICROGRAVITY,
            outcome="cool_flame",
            metrics={"extinction_diameter": Metric(value=1.4, unit="mm")},
            doi="10.60555/flex-doi",
            evidence_type=EvidenceType.MEASUREMENT,
            provenance=_provenance("flex_tests.csv", 10),
        ),
        ExperimentalTest(
            accession="PSI-69",
            investigation="FLEX",
            test_id="FLEX-02",
            fuel="n-heptane",
            fuel_phase="liquid",
            sample_geometry="droplet",
            o2_fraction=0.21,
            pressure_kpa=101.3,
            diluent="N2",
            flow_cm_s=0.0,
            gravity=Gravity.MICROGRAVITY,
            outcome="extinguished",
            doi="10.60555/flex-doi",
            evidence_type=EvidenceType.MEASUREMENT,
            provenance=_provenance("flex_tests.csv", 11),
        ),
        ExperimentalTest(
            accession="PSI-999",
            investigation="SIM",
            test_id="SIM-01",
            fuel="Cotton",
            fuel_phase="solid",
            o2_fraction=0.34,
            pressure_kpa=70.0,
            gravity=Gravity.MICROGRAVITY,
            outcome="ignited",
            evidence_type=EvidenceType.SIMULATION,
            provenance=_provenance("sim.csv", 2),
        ),
        ExperimentalTest(
            accession="PSI-999",
            investigation="SIM",
            test_id="SIM-02",
            fuel="Cotton",
            fuel_phase="solid",
            o2_fraction=0.34,
            pressure_kpa=70.0,
            gravity=Gravity.MICROGRAVITY,
            outcome="ignited",
            evidence_type=EvidenceType.MOCK,
            provenance=_provenance("mock.csv", 2, is_mock=True),
        ),
    ]
    if include_extra_test:
        tests.append(
            ExperimentalTest(
                accession="PSI-69",
                investigation="FLEX",
                test_id="FLEX-03",
                fuel="methanol",
                fuel_phase="liquid",
                o2_fraction=0.35,
                pressure_kpa=70.0,
                diluent="He",
                gravity=Gravity.MICROGRAVITY,
                outcome="extinguished",
                doi="10.60555/flex-doi",
                evidence_type=EvidenceType.MEASUREMENT,
                provenance=_provenance("flex_tests.csv", 12),
            )
        )

    write_tests_parquet(tests, snap_dir / "tests.parquet")

    chunks = [
        TextChunk(
            chunk_id="psi25-doc-1",
            accession="PSI-25",
            source_kind="document",
            source_file="BASS-II_FinalReport.pdf",
            source_url="https://psi.nasa.gov/files/BASS-II_FinalReport.pdf",
            source_version="4",
            doi="10.60555/bass2-doi",
            page=4,
            text=(
                "In BASS-II, cotton-fiberglass and Nomex fabric samples burned in elevated oxygen "
                "(34-35% O2) at 70 kPa with opposed and concurrent airflow of 10-12 cm/s."
            ),
        ),
        TextChunk(
            chunk_id="psi69-doc-1",
            accession="PSI-69",
            source_kind="document",
            source_file="FLEX_FinalReport.pdf",
            source_url="https://psi.nasa.gov/files/FLEX_FinalReport.pdf",
            source_version="3",
            doi="10.60555/flex-doi",
            page=12,
            text=(
                "FLEX heptane droplet tests with helium diluent exhibited radiative extinction "
                "followed by low-temperature cool flame combustion at 21% oxygen and 101.3 kPa."
            ),
        ),
        TextChunk(
            chunk_id="ctx-apollo-1",
            accession=None,
            source_kind="context_page",
            source_file="apollo-1.txt",
            source_url="https://www.nasa.gov/history/apollo-1/",
            text=(
                "Apollo 1 highlighted the severe flammability hazard of pure oxygen "
                "spacecraft cabins."
            ),
        ),
    ]
    (snap_dir / "chunks.jsonl").write_text(
        "\n".join(chunk.model_dump_json() for chunk in chunks) + "\n",
        encoding="utf-8",
    )

    pointer = SnapshotPointer(
        snapshot_id=snapshot_id,
        created_at=now,
        path=f"snapshots/{snapshot_id}/",
        investigation_count=len(investigations),
        test_count=len(tests),
        chunk_count=len(chunks),
        files=["tests.parquet", "investigations.json", "chunks.jsonl"],
    )
    (root_dir / "latest.json").write_text(pointer.model_dump_json(indent=2), encoding="utf-8")
    return snap_dir


@pytest.fixture(autouse=True)
def _restore_default_runtime(monkeypatch):
    for var in (
        "LLM_PROVIDER",
        "FIRELENS_LLM_PROVIDER",
        "OPENROUTER_API_KEY",
        "FIRELENS_OPENROUTER_API_KEY",
        "OPENROUTER_BASE_URL",
        "FIRELENS_OPENROUTER_BASE_URL",
        "OPENROUTER_MODEL",
        "OPENROUTER_CHAT_MODEL",
        "FIRELENS_OPENROUTER_MODEL",
        "AZURE_OPENAI_ENDPOINT",
        "FIRELENS_AZURE_OPENAI_ENDPOINT",
        "AZURE_OPENAI_API_KEY",
        "FIRELENS_AZURE_OPENAI_API_KEY",
        "OPENAI_API_KEY",
    ):
        monkeypatch.delenv(var, raising=False)
    yield
    configure_runtime(Settings(mode="mock"))


def test_settings_reads_env_and_hides_secret_from_repr(monkeypatch):
    monkeypatch.setenv("FIRELENS_MODE", "snapshot")
    monkeypatch.setenv("AZURE_OPENAI_ENDPOINT", "https://firelens-aoai.openai.azure.com")
    monkeypatch.setenv("AZURE_OPENAI_API_KEY", "super-secret-key-12345")
    monkeypatch.setenv("AZURE_OPENAI_CHAT_DEPLOYMENT", "")
    monkeypatch.setenv("AZURE_OPENAI_EMBEDDING_DEPLOYMENT", "")
    monkeypatch.setenv("AZURE_STORAGE_ACCOUNT_URL", "https://firelensdata.blob.core.windows.net")
    monkeypatch.setenv("AZURE_STORAGE_CONTAINER", "snapshots")

    settings = Settings()
    assert settings.mode == "snapshot"
    assert settings.azure_openai_endpoint == "https://firelens-aoai.openai.azure.com"
    assert settings.azure_openai_api_key == "super-secret-key-12345"
    assert settings.azure_openai_chat_deployment == "gpt-4o-mini"
    assert settings.azure_openai_embedding_deployment == "text-embedding-3-small"
    assert settings.azure_storage_account_url == "https://firelensdata.blob.core.windows.net"
    assert "super-secret-key-12345" not in repr(settings)


def test_llm_offline_embeddings_and_sql_filter():
    llm = LLMClient(Settings(mode="mock"))
    assert not llm.is_live

    v_fabric = deterministic_embed("cotton fabric combustion above 30% oxygen")
    v_solid = deterministic_embed("solid fabric flammability in elevated o2")
    v_unrelated = deterministic_embed("xyzzy gibberish token")
    assert len(v_fabric) == 128
    assert cosine_similarity(v_fabric, v_solid) > cosine_similarity(v_fabric, v_unrelated)

    sql_filter = llm.propose_sql_filter(
        "Which BASS-II fabric tests burned above 30% oxygen and below 75 kPa?"
    )
    assert sql_filter.accessions == ["PSI-25"]
    assert sql_filter.fuel_phase == "solid"
    assert sql_filter.o2_min == pytest.approx(0.30)
    assert sql_filter.pressure_max == pytest.approx(75.0)
    assert sql_filter.outcome == "ignited"

    he_filter = llm.propose_sql_filter(
        "Which FLEX tests used helium diluent and produced cool flame?"
    )
    assert he_filter.accessions == ["PSI-69"]
    assert he_filter.diluent == "He"
    assert he_filter.outcome == "cool_flame"


def test_llm_live_openai_client_calls():
    class FakeCompletions:
        def __init__(self) -> None:
            self.calls: list[dict] = []

        def create(self, **kwargs):
            self.calls.append(kwargs)
            is_json = kwargs.get("response_format", {}).get("type") == "json_object"
            content = (
                json.dumps({"fuel_phase": "solid", "o2_min": 0.30})
                if is_json
                else (
                    "Cotton fabric burned at 34% O2 "
                    "[PSI-25, 10.60555/bass2-doi, BASS-II_FinalReport.pdf p.4]."
                )
            )
            return SimpleNamespace(
                choices=[SimpleNamespace(message=SimpleNamespace(content=content))]
            )

    class FakeEmbeddings:
        def create(self, *, model: str, input: list[str]):
            return SimpleNamespace(
                data=[
                    SimpleNamespace(index=idx, embedding=[float(idx + 1), 0.5, 0.25])
                    for idx, _ in enumerate(input)
                ]
            )

    fake_client = SimpleNamespace(
        embeddings=FakeEmbeddings(),
        chat=SimpleNamespace(completions=FakeCompletions()),
    )
    llm = LLMClient(
        Settings(
            mode="snapshot",
            azure_openai_endpoint="https://example.openai.azure.com",
            azure_openai_api_key="test-key",
        ),
        openai_client=fake_client,
    )
    assert llm.is_live
    assert llm.embed_texts(["a", "b"]) == [[1.0, 0.5, 0.25], [2.0, 0.5, 0.25]]

    parsed_filter = llm.propose_sql_filter("Show fabric tests", investigation_ids=["PSI-25"])
    assert parsed_filter.accessions == ["PSI-25"]
    assert parsed_filter.fuel_phase == "solid"
    assert parsed_filter.o2_min == pytest.approx(0.30)

    chunk = TextChunk(
        chunk_id="c1",
        accession="PSI-25",
        source_kind="document",
        source_file="BASS-II_FinalReport.pdf",
        source_url="https://psi.nasa.gov/files/BASS-II_FinalReport.pdf",
        doi="10.60555/bass2-doi",
        page=4,
        text="Cotton fabric burned at 34% O2.",
    )
    from api.models import Citation

    cit = Citation(
        id="chunk:c1",
        accession="PSI-25",
        locator="BASS-II_FinalReport.pdf p.4",
        supporting_text=chunk.text,
        provenance=_provenance("BASS-II_FinalReport.pdf", None, page=4),
    )
    answer = llm.generate_grounded_answer(
        "How did cotton burn?",
        [chunk],
        [],
        [cit],
        doi_by_accession={"PSI-25": "10.60555/bass2-doi"},
    )
    assert "PSI-25" in answer


def test_openrouter_provider_configuration_and_chat_synthesis(monkeypatch):
    monkeypatch.setenv("FIRELENS_MODE", "snapshot")
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-or-v1-secret-test-key")

    settings = Settings()
    llm = LLMClient(settings)
    assert llm.provider == "openrouter"
    assert llm.is_live
    assert llm.chat_model == "openai/gpt-4o-mini"
    assert settings.openrouter_base_url == "https://openrouter.ai/api/v1"
    assert "sk-or-v1-secret-test-key" not in repr(settings)

    monkeypatch.setenv("OPENROUTER_MODEL", "openai/gpt-4.1-mini")
    custom_settings = Settings()
    custom_llm = LLMClient(custom_settings)
    assert custom_llm.chat_model == "openai/gpt-4.1-mini"

    # OpenRouter embed_texts uses instant deterministic vectors so large snapshots load fast.
    vec = llm.embed_texts(["cotton fabric oxygen 34%"])
    assert len(vec) == 1
    assert len(vec[0]) == 128

    calls: list[dict] = []

    class FakeOpenRouterCompletions:
        def create(self, **kwargs):
            calls.append(kwargs)
            is_json = kwargs.get("response_format", {}).get("type") == "json_object"
            content = (
                '```json\n{"fuel_phase": "solid", "o2_min": 0.30}\n```'
                if is_json
                else "Cotton ignited at 34% O2 [PSI-25, 10.60555/bass2-doi, BASS-II.pdf p.4]."
            )
            return SimpleNamespace(
                choices=[SimpleNamespace(message=SimpleNamespace(content=content))]
            )

    llm._client = SimpleNamespace(
        chat=SimpleNamespace(completions=FakeOpenRouterCompletions()),
    )

    sql_filter = llm.propose_sql_filter("Show cotton tests >= 30% O2", investigation_ids=["PSI-25"])
    assert sql_filter.accessions == ["PSI-25"]
    assert sql_filter.fuel_phase == "solid"
    assert sql_filter.o2_min == pytest.approx(0.30)
    assert calls[0]["model"] == "openai/gpt-4o-mini"

    from api.models import Citation

    chunk = TextChunk(
        chunk_id="or-c1",
        accession="PSI-25",
        source_kind="document",
        source_file="BASS-II.pdf",
        source_url="https://psi.nasa.gov/files/BASS-II.pdf",
        doi="10.60555/bass2-doi",
        page=4,
        text="Cotton fabric burned at 34% O2.",
    )
    cit = Citation(
        id="chunk:or-c1",
        accession="PSI-25",
        locator="BASS-II.pdf p.4",
        supporting_text=chunk.text,
        provenance=_provenance("BASS-II.pdf", None, page=4),
    )
    answer = llm.generate_grounded_answer(
        "How did cotton burn?",
        [chunk],
        [],
        [cit],
        doi_by_accession={"PSI-25": "10.60555/bass2-doi"},
    )
    assert "PSI-25" in answer
    assert calls[1]["model"] == "openai/gpt-4o-mini"


def test_snapshot_loader_local_and_15min_hotswap(tmp_path: Path):
    _build_synthetic_snapshot(tmp_path, snapshot_id="v1", include_extra_test=False)
    current_time = [1000.0]
    loader = SnapshotLoader(
        Settings(mode="snapshot", snapshots_dir=tmp_path, snapshot_refresh_seconds=900),
        clock=lambda: current_time[0],
    )

    snap1 = loader.get_snapshot()
    assert snap1.snapshot_id == "v1"
    assert snap1.test_count == 8
    assert not snap1.is_sample_fallback

    # Write v2 pointer, but check before 15 minutes (900s) elapse -> stays on v1.
    _build_synthetic_snapshot(tmp_path, snapshot_id="v2", include_extra_test=True)
    current_time[0] = 1899.0
    assert loader.get_snapshot().snapshot_id == "v1"

    # At +900s, pointer is re-checked and snapshot v2 hot-swaps in memory.
    current_time[0] = 1900.0
    snap2 = loader.get_snapshot()
    assert snap2.snapshot_id == "v2"
    assert snap2.test_count == 9


def test_snapshot_loader_azure_blob_and_sample_fallback(tmp_path: Path):
    source_root = tmp_path / "remote_src"
    snap_dir = _build_synthetic_snapshot(source_root, snapshot_id="blob-v1")
    blobs = {
        "latest.json": (source_root / "latest.json").read_bytes(),
        "blob-v1/tests.parquet": (snap_dir / "tests.parquet").read_bytes(),
        "blob-v1/investigations.json": (snap_dir / "investigations.json").read_bytes(),
        "blob-v1/chunks.jsonl": (snap_dir / "chunks.jsonl").read_bytes(),
    }

    cache_root = tmp_path / "local_cache"
    loader = SnapshotLoader(
        Settings(
            mode="snapshot",
            snapshots_dir=cache_root,
            azure_storage_account_url="https://firelensdata.blob.core.windows.net",
        ),
        blob_fetcher=blobs.get,
    )
    snap = loader.get_snapshot()
    assert snap.snapshot_id == "blob-v1"
    assert snap.test_count == 8
    assert (cache_root / "blob-v1/tests.parquet").exists()

    # Without latest.json or blob, falls back cleanly to baked-in snapshots/sample.
    empty_dir = tmp_path / "empty_snapshots"
    empty_dir.mkdir()
    fallback_loader = SnapshotLoader(Settings(mode="snapshot", snapshots_dir=empty_dir))
    fallback = fallback_loader.get_snapshot()
    assert fallback.is_sample_fallback
    assert fallback.test_count == 0
    assert len(fallback.investigations) == 5


def test_meta_counts_and_hourly_cached_catalogue_check(tmp_path: Path):
    _build_synthetic_snapshot(tmp_path, snapshot_id="snap-meta-1")
    current_time = [100.0]
    calls = [0]

    def fake_catalogue() -> list[dict]:
        calls[0] += 1
        return [
            {
                "_source": {
                    "Accession": "PSI-25",
                    "Version": "4",
                    "Research Area": "Combustion Science",
                }
            },
            {
                "_source": {
                    "Accession": "PSI-69",
                    "Version": "4",
                    "Research Area": "Combustion Science",
                }
            },
            {
                "_source": {
                    "Accession": "PSI-200",
                    "Version": "1",
                    "Research Area": "Combustion Science",
                }
            },
            {
                "_source": {
                    "Accession": "PSI-998",
                    "Version": "1",
                    "Research Area": "Materials Science",
                }
            },
        ]

    configure_runtime(
        Settings(mode="snapshot", snapshots_dir=tmp_path, catalogue_cache_seconds=3600),
        catalogue_fetcher=fake_catalogue,
        clock=lambda: current_time[0],
    )
    client = TestClient(app)

    res1 = client.get("/meta")
    assert res1.status_code == 200
    meta1 = MetaResponse.model_validate(res1.json())
    assert meta1.snapshot_id == "snap-meta-1"
    assert meta1.investigation_count == 4
    assert meta1.test_count == 8
    assert meta1.new_releases_since_snapshot == 2  # PSI-69 bumped 3->4 + PSI-200 new
    assert meta1.catalogue_checked_at is not None
    assert calls[0] == 1

    # Second call within 1 hour hits cache.
    current_time[0] = 3699.0
    res2 = client.get("/meta")
    assert res2.status_code == 200
    assert calls[0] == 1

    # Call after 1 hour refreshes from PSI catalogue.
    current_time[0] = 3700.0
    res3 = client.get("/meta")
    assert res3.status_code == 200
    assert calls[0] == 2


def test_investigations_detail_documents_and_related_studies(tmp_path: Path):
    _build_synthetic_snapshot(tmp_path)
    configure_runtime(Settings(snapshots_dir=tmp_path))  # auto-detect snapshot from latest.json
    client = TestClient(app)

    listed = client.get("/investigations?q=BASS").json()
    assert listed["total"] == 1
    assert listed["items"][0]["accession"] == "PSI-25"

    detail = Investigation.model_validate(client.get("/investigations/PSI-25").json())
    assert detail.doi == "10.60555/bass2-doi"
    assert detail.summary is not None
    assert len(detail.documents) == 1
    assert detail.related_investigations  # populated automatically from hardware/phase/similarity
    assert "PSI-25" not in detail.related_investigations


def test_rank_cfmd_math_profile_reranking_and_gaps(tmp_path: Path):
    _build_synthetic_snapshot(tmp_path)
    configure_runtime(Settings(mode="snapshot", snapshots_dir=tmp_path))
    client = TestClient(app)

    moon = RankResponse.model_validate(client.get("/rank?profile=moon_base&goal=prevention").json())
    by_acc = {item.accession: item for item in moon.items}

    # Verify PSI-25 math for moon_base (O2 >= 0.30, P <= 70.3265 kPa, goal=prevention):
    # Individual measurement rows = 3 (BASS2-01, BASS2-02, BASS2-03; BASS2-GROUP excluded).
    # Matching rows = 2/3 -> C = 0.6667
    # Fuel phase = solid -> F = 1.0
    # Goal prevention in ["prevention", "suppression"] -> M = 1.0
    # D = min(1.0, (0.20 + 0.30*(3/50)) + 0.25 + 0.15 + 0.10) = 0.718
    # R = 0.40*0.6667 + 0.25*1.0 + 0.20*1.0 + 0.15*0.718 = 0.8244
    psi25 = by_acc["PSI-25"]
    assert psi25.score == pytest.approx(0.8244, abs=1e-4)
    assert psi25.breakdown["conditions"] == pytest.approx(0.6667, abs=1e-4)
    assert psi25.breakdown["fuel_realism"] == pytest.approx(1.0)
    assert psi25.breakdown["safety_goal"] == pytest.approx(1.0)
    assert psi25.breakdown["data_richness"] == pytest.approx(0.718, abs=1e-4)
    assert "No partial-gravity test rows in PSI snapshot" in psi25.gaps

    # PSI-69 has 0/2 rows matching Moon-base conditions -> ranks below PSI-25.
    psi69 = by_acc["PSI-69"]
    assert psi69.score is not None and psi69.score < psi25.score
    assert "No tests within target oxygen envelope" in psi69.gaps

    # PSI-100 (0 rows) and PSI-999 (simulated + mock only) must keep score=None with explicit gaps.
    assert by_acc["PSI-100"].score is None
    assert by_acc["PSI-999"].score is None
    assert "grouped, mock or non-measurement" in by_acc["PSI-999"].gaps[0]

    # Under ISS profile (21% O2, 101.35 kPa), PSI-69 has C=1.0 while PSI-25 has C=1/3.
    iss = RankResponse.model_validate(client.get("/rank?profile=iss&goal=suppression").json())
    iss_by_acc = {item.accession: item for item in iss.items}
    assert iss_by_acc["PSI-69"].breakdown["conditions"] == pytest.approx(1.0)
    assert iss_by_acc["PSI-25"].breakdown["conditions"] == pytest.approx(0.3333, abs=1e-4)

    # Custom profile with flow_cm_s + partial gravity filters rows missing flow_cm_s.
    custom = RankResponse.model_validate(
        client.get(
            "/rank?profile=custom&o2_fraction=0.34&pressure_kpa=70&flow_cm_s=10&gravity_level_g=0.1667"
        ).json()
    )
    custom_25 = next(item for item in custom.items if item.accession == "PSI-25")
    # BASS2-03 has flow_cm_s=None, so only BASS2-01 and BASS2-02 are valid (2/2 match 10+-5 cm/s).
    assert custom_25.breakdown["conditions"] == pytest.approx(1.0)
    assert "No partial-gravity test rows in PSI snapshot" in custom_25.gaps


def test_tests_duckdb_filtering_and_pagination(tmp_path: Path):
    _build_synthetic_snapshot(tmp_path)
    configure_runtime(Settings(mode="snapshot", snapshots_dir=tmp_path))
    client = TestClient(app)

    filtered = ExperimentListContract.model_validate(
        client.get("/tests?accession=PSI-25&oxygen_min=0.30&pressure_max=80").json()
    )
    assert filtered.total == 3  # BASS2-01, BASS2-02, BASS2-GROUP match O2>=0.30 and P<=80
    assert {row.test_id for row in filtered.items} == {"BASS2-01", "BASS2-02", "BASS2-GROUP"}

    paged = ExperimentListContract.model_validate(client.get("/tests?limit=2&offset=2").json())
    assert paged.total == 8
    assert len(paged.items) == 2


def test_compare_field_grounded_summary(tmp_path: Path):
    _build_synthetic_snapshot(tmp_path)
    configure_runtime(Settings(mode="snapshot", snapshots_dir=tmp_path))
    client = TestClient(app)

    res = CompareResponse.model_validate(client.get("/compare?ids=PSI-25,PSI-69").json())
    assert len(res.investigations) == 2
    assert any("Combustion Science" in s for s in res.same)
    assert any("International Space Station" in s for s in res.same)
    assert any("Fuel phase:" in d and "solid" in d and "liquid" in d for d in res.different)
    assert "PSI-25, PSI-69" in res.summary
    assert "10.60555/bass2-doi" in " ".join(res.different)


def test_export_csv_and_json_with_citations_and_nulls(tmp_path: Path):
    _build_synthetic_snapshot(tmp_path)
    configure_runtime(Settings(mode="snapshot", snapshots_dir=tmp_path))
    client = TestClient(app)

    csv_resp = client.get("/export?format=csv&accession=PSI-25&oxygen_max=0.25")
    assert csv_resp.status_code == 200
    lines = csv_resp.text.splitlines()
    assert lines[0].startswith("# Source: NASA Physical Sciences Informatics")
    assert "10.60555/bass2-doi" in lines[0]

    reader = csv.DictReader(io.StringIO("\n".join(lines[1:])))
    rows = list(reader)
    assert len(rows) == 1
    assert rows[0]["test_id"] == "BASS2-03"
    assert rows[0]["doi"] == "10.60555/bass2-doi"
    assert rows[0]["source_file"] == "bass2_tests.csv"
    assert rows[0]["source_row"] == "4"
    assert rows[0]["flow_cm_s"] == ""  # missing value stays empty in CSV

    json_resp = ExportResponse.model_validate(
        client.get("/export?format=json&accession=PSI-69").json()
    )
    assert "10.60555/flex-doi" in json_resp.source_credit
    assert len(json_resp.tests) == 2
    assert all(t.accession == "PSI-69" for t in json_resp.tests)


def _parse_sse(body: str) -> list[tuple[str, dict]]:
    frames: list[tuple[str, dict]] = []
    for raw_frame in body.strip().split("\n\n"):
        if not raw_frame.strip():
            continue
        lines = raw_frame.splitlines()
        event = lines[0].removeprefix("event: ")
        payload = json.loads(lines[1].removeprefix("data: "))
        frames.append((event, payload))
    return frames


def test_chat_sse_grounded_citations_abstention_out_of_scope_and_rate_limit(tmp_path: Path):
    _build_synthetic_snapshot(tmp_path)
    configure_runtime(
        Settings(mode="snapshot", snapshots_dir=tmp_path, chat_rate_limit_per_minute=2)
    )
    client = TestClient(app)

    # 1. Grounded question retrieves chunks + SQL rows and emits mandatory citations.
    r1 = client.post(
        "/chat",
        json={"question": "Which fabric tests burned above 30% oxygen and at what airflow?"},
        headers={"X-Forwarded-For": "198.51.100.10"},
    )
    assert r1.status_code == 200
    frames1 = _parse_sse(r1.text)
    assert [name for name, _ in frames1] == ["progress", "progress", "answer", "done"]
    ProgressEvent.model_validate(frames1[0][1])
    ProgressEvent.model_validate(frames1[1][1])
    ans1 = AnswerEvent.model_validate(frames1[2][1])
    done1 = DoneEvent.model_validate(frames1[3][1])
    assert ans1.status == "supported"
    assert done1.finish_reason == "stop"
    assert any(c.accession == "PSI-25" for c in ans1.citations)
    assert any(c.id.startswith("row:PSI-25:") for c in ans1.citations)
    assert "PSI-25" in ans1.text

    # 2. Out-of-scope rocket/propellant query refuses without fabricating citations.
    r_oos = client.post(
        "/chat",
        json={"question": "What hypergolic rocket propellants burn best in thrusters?"},
        headers={"X-Forwarded-For": "198.51.100.10"},
    )
    assert r_oos.status_code == 200
    frames_oos = _parse_sse(r_oos.text)
    ans_oos = AnswerEvent.model_validate(frames_oos[1][1])
    assert ans_oos.status == "insufficient_evidence"
    assert ans_oos.citations == []
    assert "out of scope" in ans_oos.text.casefold()

    # 3. Third request from the same IP within 1 minute hits per-IP rate limit (429).
    r_limited = client.post(
        "/chat",
        json={"question": "Tell me about FLEX helium tests"},
        headers={"X-Forwarded-For": "198.51.100.10"},
    )
    assert r_limited.status_code == 429

    # 4. A different connection address has its own bucket; headers are not trusted.
    other_client = TestClient(app, client=("198.51.100.20", 50000))
    r_gibberish = other_client.post(
        "/chat",
        json={"question": "zzzzqqqq wwwwkkkk"},
        headers={"X-Forwarded-For": "198.51.100.20"},
    )
    assert r_gibberish.status_code == 200
    frames_g = _parse_sse(r_gibberish.text)
    ans_g = AnswerEvent.model_validate(frames_g[1][1])
    assert ans_g.status == "insufficient_evidence"
    assert ans_g.citations == []

    # 5. Partial-gravity query returns grounded 0g context plus explicit partial-g gap notice.
    r_lunar = other_client.post(
        "/chat",
        json={"question": "What partial-gravity lunar fabric burning tests exist in PSI-25?"},
        headers={"X-Forwarded-For": "198.51.100.20"},
    )
    assert r_lunar.status_code == 200
    frames_l = _parse_sse(r_lunar.text)
    ans_l = AnswerEvent.model_validate(frames_l[2][1])
    assert ans_l.status == "supported"
    assert "no partial-gravity" in ans_l.text.casefold()


def test_interoperability_with_harvest_validate_tests_parquet(tmp_path: Path):
    """Ensure Phase 6 DuckDB reader handles Arrow struct/timestamp Parquet from Phase 4."""
    from harvest.validation import validate_tests

    snap_dir = _build_synthetic_snapshot(tmp_path, snapshot_id="arrow-interop")
    row = ExperimentalTest(
        accession="PSI-25",
        investigation="BASS-II",
        test_id="ARROW-01",
        test_date="2026-01-15",
        fuel="Cotton",
        fuel_phase="solid",
        sample_dimensions_mm={"width": 20.0},
        o2_fraction=0.34,
        pressure_kpa=70.0,
        diluent="N2",
        diluent_fractions={"N2": 0.66},
        flow_cm_s=10.0,
        gravity=Gravity.MICROGRAVITY,
        outcome="ignited",
        metrics={"burn_time": Metric(value=15.0, unit="s")},
        doi="10.60555/bass2-doi",
        evidence_type=EvidenceType.MEASUREMENT,
        provenance=_provenance("arrow.csv", 2),
    )
    df = validate_tests([row])
    df.to_parquet(snap_dir / "tests.parquet", index=False)

    configure_runtime(Settings(mode="snapshot", snapshots_dir=tmp_path))
    client = TestClient(app)

    tests_resp = ExperimentListContract.model_validate(client.get("/tests?accession=PSI-25").json())
    assert tests_resp.total == 1
    assert tests_resp.items[0].test_id == "ARROW-01"
    assert tests_resp.items[0].metrics["burn_time"].value == pytest.approx(15.0)

    rank_resp = RankResponse.model_validate(client.get("/rank?profile=moon_base").json())
    psi25 = next(item for item in rank_resp.items if item.accession == "PSI-25")
    assert psi25.breakdown["conditions"] == pytest.approx(1.0)


def test_phase4_5_pipeline_snapshot_serves_phase6_api_end_to_end(tmp_path: Path):
    """Run Phases 4-5 run_pipeline(stage='all') and verify all Phase 6 endpoints serve it."""
    import pymupdf
    import yaml

    from harvest.pipeline import run_pipeline

    raw_dir = tmp_path / "raw"
    acc1 = raw_dir / "PSI-501"
    acc2 = raw_dir / "PSI-502"
    (acc1 / "documents").mkdir(parents=True)
    acc2.mkdir(parents=True)
    maps_dir = tmp_path / "maps"
    maps_dir.mkdir()
    snaps_dir = tmp_path / "snapshots"

    (acc1 / "manifest.json").write_text(
        json.dumps(
            {
                "accession": "PSI-501",
                "title": "Microgravity Solid Cotton Flammability",
                "version": "1",
                "doi": "10.60555/psi-501",
                "experimentHardware": "MSG Flow Duct",
                "flightProgram": "International Space Station (ISS)",
                "objective": "Measure solid fabric ignition in elevated oxygen and airflow.",
            }
        ),
        encoding="utf-8",
    )
    (acc1 / "tests.csv").write_text(
        "TestId,Fuel,XO2,P_kPa,Flow,Outcome,SpreadRate\n"
        "S1,Cotton fabric,0.34,70.0,10.0,Ignited,1.9\n"
        "S2,Cotton fabric,0.21,101.3,10.0,No Ignition,\n",
        encoding="utf-8",
    )
    pdf_doc = pymupdf.open()
    page = pdf_doc.new_page()
    page.insert_text(
        (72, 72),
        "PSI-501 Cotton fabric ignited at 34% O2 and 70 kPa with 10 cm/s airflow in MSG Flow Duct.",
    )
    pdf_doc.save(str(acc1 / "documents" / "psi501_report.pdf"))
    pdf_doc.close()

    (acc2 / "manifest.json").write_text(
        json.dumps(
            {
                "accession": "PSI-502",
                "title": "Droplet Extinction Reference Study",
                "version": "1",
                "doi": "10.60555/psi-502",
                "experimentHardware": "Combustion Chamber",
                "flightProgram": "International Space Station (ISS)",
                "objective": "Measure liquid heptane droplet extinction at atmospheric air.",
            }
        ),
        encoding="utf-8",
    )
    (acc2 / "tests.csv").write_text(
        "TestId,Fuel,XO2,P_kPa,Outcome\nL1,n-heptane,0.21,101.3,Extinguished\n",
        encoding="utf-8",
    )

    (maps_dir / "PSI-501.yaml").write_text(
        yaml.safe_dump(
            {
                "schema_version": 1,
                "accession": "PSI-501",
                "source_file": "tests.csv",
                "id_column": "TestId",
                "default_fuel_phase": "solid",
                "columns": {
                    "fuel": {"source_column": "Fuel"},
                    "o2_fraction": {"source_column": "XO2", "multiplier": 1.0},
                    "pressure_kpa": {"source_column": "P_kPa", "unit": "kPa"},
                    "flow_cm_s": {"source_column": "Flow", "unit": "cm/s"},
                    "outcome": {"source_column": "Outcome"},
                },
                "metrics": {"spread_rate": {"source_column": "SpreadRate", "unit": "cm/s"}},
                "outcome_map": {"Ignited": "ignited", "No Ignition": "extinguished"},
            }
        ),
        encoding="utf-8",
    )
    (maps_dir / "PSI-502.yaml").write_text(
        yaml.safe_dump(
            {
                "schema_version": 1,
                "accession": "PSI-502",
                "source_file": "tests.csv",
                "id_column": "TestId",
                "default_fuel_phase": "liquid",
                "columns": {
                    "fuel": {"source_column": "Fuel"},
                    "o2_fraction": {"source_column": "XO2", "multiplier": 1.0},
                    "pressure_kpa": {"source_column": "P_kPa", "unit": "kPa"},
                    "outcome": {"source_column": "Outcome"},
                },
                "outcome_map": {"Extinguished": "extinguished"},
            }
        ),
        encoding="utf-8",
    )

    run_pipeline(
        stage="all",
        raw_dir=raw_dir,
        maps_dir=maps_dir,
        snapshots_dir=snaps_dir,
        snapshot_id="p45-e2e",
    )

    configure_runtime(Settings(mode="snapshot", snapshots_dir=snaps_dir))
    client = TestClient(app)

    meta_resp = MetaResponse.model_validate(client.get("/meta").json())
    assert meta_resp.snapshot_id == "p45-e2e"
    assert meta_resp.investigation_count == 2
    assert meta_resp.test_count == 3
    assert not any("sample fallback" in w.lower() for w in meta_resp.warnings)

    inv_list = InvestigationList.model_validate(client.get("/investigations").json())
    assert {inv.accession for inv in inv_list.items} == {"PSI-501", "PSI-502"}

    rank_resp = RankResponse.model_validate(
        client.get("/rank?profile=moon_base&goal=prevention").json()
    )
    assert rank_resp.items[0].accession == "PSI-501"
    assert rank_resp.items[0].score is not None

    tests_resp = ExperimentListContract.model_validate(
        client.get("/tests?accession=PSI-501&oxygen_min=0.30").json()
    )
    assert tests_resp.total == 1
    assert tests_resp.items[0].test_id == "S1"

    cmp_resp = CompareResponse.model_validate(client.get("/compare?ids=PSI-501,PSI-502").json())
    assert len(cmp_resp.investigations) == 2

    csv_resp = client.get("/export?format=csv&accession=PSI-501")
    assert csv_resp.status_code == 200
    assert "10.60555/psi-501" in csv_resp.text
    assert "S1" in csv_resp.text

    chat_resp = client.post(
        "/chat",
        json={"question": "Which fabric tests in PSI-501 burned at 34% O2 and 70 kPa?"},
        headers={"X-Forwarded-For": "198.51.100.77"},
    )
    assert chat_resp.status_code == 200
    frames = _parse_sse(chat_resp.text)
    ans = AnswerEvent.model_validate(frames[-2][1])
    assert ans.status == "supported"
    assert any(c.accession == "PSI-501" for c in ans.citations)


def test_real_local_snapshot_serves_phase6_api_when_present():
    """Verify git-ignored local NASA PSI snapshot serves all Phase 6 routes when present."""
    from api.config import ROOT

    if not (ROOT / "snapshots/latest.json").exists():
        pytest.skip("Local snapshots/latest.json not generated in this environment.")

    configure_runtime(Settings(mode="snapshot"))
    client = TestClient(app)

    meta_resp = MetaResponse.model_validate(client.get("/meta").json())
    assert meta_resp.investigation_count == 24
    pointer = json.loads((ROOT / "snapshots/latest.json").read_text())
    assert meta_resp.test_count == pointer["test_count"]

    moon_rank = RankResponse.model_validate(client.get("/rank?profile=moon_base").json())
    assert len(moon_rank.items) == 24
    assert any(item.score is not None for item in moon_rank.items)

    iss_rank = RankResponse.model_validate(client.get("/rank?profile=iss").json())
    assert len(iss_rank.items) == 24

    tests_resp = ExperimentListContract.model_validate(
        client.get("/tests?accession=PSI-69&limit=5").json()
    )
    assert tests_resp.total == 274
    assert len(tests_resp.items) == 5

    cmp_resp = CompareResponse.model_validate(client.get("/compare?ids=PSI-25,PSI-69").json())
    assert len(cmp_resp.investigations) == 2

    csv_resp = client.get("/export?format=csv&accession=PSI-102")
    assert csv_resp.status_code == 200
    assert "PSI-102" in csv_resp.text

    chat_resp = client.post(
        "/chat",
        json={"question": "Which FLEX tests in PSI-69 observed cool flame behavior?"},
        headers={"X-Forwarded-For": "198.51.100.88"},
    )
    assert chat_resp.status_code == 200
    frames = _parse_sse(chat_resp.text)
    ans = AnswerEvent.model_validate(frames[-2][1])
    assert ans.status == "supported"
    assert any(c.accession == "PSI-69" for c in ans.citations)


@pytest.mark.parametrize(
    "payload",
    [
        {"claims": [{"citation_id": "chunk:unknown", "quote": "fabric"}]},
        {"claims": [{"citation_id": "chunk:psi25-doc-1", "quote": "999% oxygen"}]},
        {"claims": [{"citation_id": "chunk:psi25-doc-1", "quote": ""}]},
        {
            "claims": [
                {"citation_id": "chunk:psi25-doc-1", "quote": "fabric"},
                {"citation_id": "chunk:invented", "quote": "safe"},
            ]
        },
        {"answer": "PSI-25 proves all materials safe at 999% oxygen"},
    ],
)
def test_live_answer_rejects_unsupported_claims(tmp_path, payload):
    _build_synthetic_snapshot(tmp_path)
    runtime = configure_runtime(Settings(mode="snapshot", snapshots_dir=tmp_path))
    snap = runtime.snapshot_loader.get_snapshot()
    from api.rag import build_citations

    chunks = snap.chunks[:1]
    citations = build_citations(snap, chunks, [])
    fake = SimpleNamespace(
        chat=SimpleNamespace(
            completions=SimpleNamespace(
                create=lambda **kwargs: SimpleNamespace(
                    choices=[SimpleNamespace(message=SimpleNamespace(content=json.dumps(payload)))]
                )
            )
        )
    )
    llm = LLMClient(Settings(mode="snapshot"), openai_client=fake)
    answer = llm.generate_grounded_answer("fabric oxygen", chunks, [], citations)
    assert "999%" not in answer
    assert "chunk:invented" not in answer
    assert "PSI-25" in answer


def test_live_answer_renders_only_verified_quote(tmp_path):
    _build_synthetic_snapshot(tmp_path)
    runtime = configure_runtime(Settings(mode="snapshot", snapshots_dir=tmp_path))
    snap = runtime.snapshot_loader.get_snapshot()
    from api.rag import build_citations

    citations = build_citations(snap, snap.chunks[:1], [])
    citation = citations[0]
    payload = {"claims": [{"citation_id": citation.id, "quote": citation.supporting_text}]}
    fake = SimpleNamespace(
        chat=SimpleNamespace(
            completions=SimpleNamespace(
                create=lambda **kwargs: SimpleNamespace(
                    choices=[SimpleNamespace(message=SimpleNamespace(content=json.dumps(payload)))]
                )
            )
        )
    )
    llm = LLMClient(Settings(mode="snapshot"), openai_client=fake)
    answer = llm.generate_grounded_answer("fabric", snap.chunks[:1], [], citations)
    assert "Retrieved source excerpts" in answer
    assert citation.supporting_text in answer
    assert f", {citation.locator}]" in answer


def test_chat_excludes_grouped_mock_and_simulated_measurement_rows(tmp_path):
    _build_synthetic_snapshot(tmp_path)
    runtime = configure_runtime(Settings(mode="snapshot", snapshots_dir=tmp_path))
    from api.llm import SqlRowFilter
    from api.rag import retrieve_top_chunks

    rows = runtime.snapshot_loader.query_tests_by_sql_filter(SqlRowFilter())
    assert rows
    assert all(r.evidence_type == EvidenceType.MEASUREMENT for r in rows)
    snap = runtime.snapshot_loader.get_snapshot()
    chunks = retrieve_top_chunks("PSI-25 fabric oxygen", snap, runtime.llm)
    assert any(c.accession == "PSI-25" for c in chunks)
    assert all(r.record_kind == "individual_test" and not r.provenance.is_mock for r in rows)
    snap.investigations_by_id["PSI-999"].fixture = True
    client = TestClient(app)
    answer = _parse_sse(
        client.post("/chat", json={"question": "fabric", "investigation_ids": ["PSI-999"]}).text
    )[-2][1]
    assert answer["status"] == "insufficient_evidence"
    assert answer["citations"] == []


def test_chat_abstention_is_not_labelled_supported(tmp_path, monkeypatch):
    _build_synthetic_snapshot(tmp_path)
    runtime = configure_runtime(Settings(mode="snapshot", snapshots_dir=tmp_path))
    monkeypatch.setattr(
        runtime.llm,
        "generate_grounded_answer",
        lambda *a, **kw: "Insufficient evidence: sources do not answer the question.",
    )
    response = TestClient(app).post("/chat", json={"question": "PSI-25 fabric tests"})
    frames = _parse_sse(response.text)
    assert frames[-2][1]["status"] == "insufficient_evidence"
    assert frames[-2][1]["citations"] == []
    assert frames[-1][1]["finish_reason"] == "insufficient_evidence"


def test_forwarding_headers_cannot_bypass_chat_limit(tmp_path):
    _build_synthetic_snapshot(tmp_path)
    configure_runtime(
        Settings(mode="snapshot", snapshots_dir=tmp_path, chat_rate_limit_per_minute=1)
    )
    client = TestClient(app, client=("198.51.100.30", 50000))
    assert (
        client.post(
            "/chat", json={"question": "fabric"}, headers={"X-Forwarded-For": "1.1.1.1"}
        ).status_code
        == 200
    )
    assert (
        client.post(
            "/chat",
            json={"question": "fabric"},
            headers={"X-Forwarded-For": "2.2.2.2", "Forwarded": "for=3.3.3.3"},
        ).status_code
        == 429
    )
    other = TestClient(app, client=("198.51.100.31", 50000))
    assert other.post("/chat", json={"question": "fabric"}).status_code == 200


def test_absent_summary_is_not_retrieved(tmp_path):
    _build_synthetic_snapshot(tmp_path)
    runtime = configure_runtime(Settings(mode="snapshot", snapshots_dir=tmp_path))
    snap = runtime.snapshot_loader.get_snapshot()
    from api.rag import retrieve_top_chunks

    summary = snap.chunks[0].model_copy(
        update={"chunk_id": "absent-summary", "source_kind": "summary"}
    )
    snap.chunks.append(summary)
    snap.chunk_embeddings.append(runtime.llm.embed_text(summary.text))
    snap.investigations_by_id["PSI-25"].summary = None
    chunks = retrieve_top_chunks("PSI-25 fabric", snap, runtime.llm)
    assert all(c.chunk_id != "absent-summary" for c in chunks)
    assert any(c.accession == "PSI-25" for c in chunks)


def test_live_model_abstention_survives_to_sse(tmp_path):
    _build_synthetic_snapshot(tmp_path)
    fake = SimpleNamespace(
        chat=SimpleNamespace(
            completions=SimpleNamespace(
                create=lambda **kwargs: SimpleNamespace(
                    choices=[
                        SimpleNamespace(
                            message=SimpleNamespace(
                                content=json.dumps({"claims": [], "insufficient_evidence": True})
                            )
                        )
                    ]
                )
            )
        )
    )
    configure_runtime(Settings(mode="snapshot", snapshots_dir=tmp_path), openai_client=fake)
    frames = _parse_sse(
        TestClient(app).post("/chat", json={"question": "PSI-25 fabric tests"}).text
    )
    assert frames[-2][1]["status"] == "insufficient_evidence"
    assert frames[-2][1]["citations"] == []
    assert frames[-1][1]["finish_reason"] == "insufficient_evidence"


def test_comparative_spread_retrieval_prioritizes_findings_not_operations(tmp_path):
    from api.rag import retrieve_top_chunks

    _build_synthetic_snapshot(tmp_path)
    runtime = configure_runtime(
        Settings(mode="snapshot", snapshots_dir=tmp_path, llm_provider="offline")
    )
    snap = runtime.snapshot_loader.get_snapshot()
    base = snap.chunks[0]
    texts = [
        "Flame experiment report. Reduced emissions. Crew installed flame experiment bottles.",
        "Opposed-flow flame spread rate increases to a maximum "
        "and then decreases at higher flow speeds.",
        "Reduced gravity experiments involve flame operations on the station.",
    ]
    snap.chunks = [
        base.model_copy(update={"chunk_id": f"probe-{i}", "text": text})
        for i, text in enumerate(texts)
    ]
    snap.chunk_embeddings = [runtime.llm.embed_text(text) for text in texts]
    chunks = retrieve_top_chunks(
        "Which experiments report reduced flame spread?", snap, runtime.llm
    )
    assert chunks[0].chunk_id == "probe-1"
    assert all("spread" in c.text for c in chunks)


def test_real_comparative_spread_question_finds_citable_bass_result():
    from api.config import ROOT
    from api.llm import deterministic_grounded_answer
    from api.rag import build_citations, retrieve_top_chunks

    if not (ROOT / "snapshots/latest.json").exists():
        pytest.skip("Local source snapshot required")
    runtime = configure_runtime(
        Settings(
            mode="snapshot", llm_provider="offline", azure_storage_account_url="", _env_file=None
        )
    )
    snap = runtime.snapshot_loader.get_snapshot()
    question = "Which experiments report reduced flame spread?"
    chunks = retrieve_top_chunks(question, snap, runtime.llm)
    assert any(
        c.accession == "PSI-26" and "decreases at higher speeds" in c.text for c in chunks[:4]
    )
    answer = deterministic_grounded_answer(question, chunks, [], build_citations(snap, chunks, []))
    assert "decreases at higher speeds" in answer
    assert "PSI-26" in answer
    assert "Gap notice" not in answer


def test_cancelled_chat_does_not_start_model_or_loader_work():
    from api.models import ChatRequest
    from api.rag import stream_chat_events

    class UnexpectedWork:
        def __getattr__(self, name):
            raise AssertionError(f"Cancelled request accessed {name}")

    assert (
        list(
            stream_chat_events(
                ChatRequest(question="flame spread"),
                loader=UnexpectedWork(),
                llm=UnexpectedWork(),
                mock_mode=False,
                cancelled=lambda: True,
            )
        )
        == []
    )
