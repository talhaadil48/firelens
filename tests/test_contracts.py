import json

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from api.config import ROOT, load_profiles
from api.main import app
from api.models import (
    AnswerEvent,
    CompareResponse,
    DoneEvent,
    ExportResponse,
    Investigation,
    InvestigationList,
    MetaResponse,
    ProgressEvent,
    RankResponse,
)
from api.models import (
    TestList as ExperimentListContract,
)
from scripts.export_contracts import outputs

client = TestClient(app)


@pytest.mark.parametrize(
    ("url", "model"),
    [
        ("/meta", MetaResponse),
        ("/investigations", InvestigationList),
        ("/investigations/PSI-69", Investigation),
        ("/rank?profile=moon_base", RankResponse),
        ("/tests", ExperimentListContract),
        ("/compare?ids=PSI-26,PSI-25", CompareResponse),
        ("/export?format=json", ExportResponse),
    ],
)
def test_endpoints_match_contract(url, model):
    response = client.get(url)
    assert response.status_code == 200
    model.model_validate(response.json())


def test_metadata_has_real_sources_without_fabricated_measurements():
    items = client.get("/investigations").json()["items"]
    assert {item["accession"] for item in items} == {
        "PSI-26",
        "PSI-69",
        "PSI-159",
        "PSI-100",
        "PSI-25",
    }
    assert all(item["citations"][0]["provenance"]["source_sha256"] for item in items)
    assert all(item["fixture"] and item["test_count"] == 0 for item in items)
    assert client.get("/tests").json()["items"] == []
    ranking = client.get("/rank").json()
    assert all(item["score"] is None for item in ranking["items"])


def test_profile_override_is_returned_and_does_not_mutate_defaults():
    result = client.get("/rank?profile=iss&oxygen_fraction=0.4&pressure_kpa=70&flow_cm_s=3").json()
    assert result["profile"]["oxygen"]["minimum"] == 0.4
    assert result["profile"]["pressure"]["maximum"] == 70
    assert result["profile"]["flow"]["minimum"] == 3
    assert client.get("/rank?profile=iss").json()["profile"]["oxygen"]["minimum"] == 0.21


def test_investigation_filter_and_pagination():
    assert client.get("/investigations?q=PSI-69").json()["total"] == 1
    assert len(client.get("/investigations?limit=2&offset=1").json()["items"]) == 2
    assert client.get("/investigations?q=no-such-study").json()["total"] == 0


@pytest.mark.parametrize(
    "url",
    [
        "/rank?profile=unknown",
        "/investigations/PSI-99999",
        "/tests?accession=PSI-99999",
    ],
)
def test_unknown_resources_return_404(url):
    assert client.get(url).status_code == 404


@pytest.mark.parametrize(
    "url",
    [
        "/compare?ids=PSI-26",
        "/compare?ids=PSI-26,PSI-26",
        "/rank?oxygen_fraction=1.1",
        "/rank?pressure_kpa=0",
        "/rank?flow_cm_s=-1",
        "/tests?oxygen_min=0.5&oxygen_max=0.2",
        "/tests?pressure_min=100&pressure_max=50",
        "/investigations?limit=0",
        "/export?format=xml",
    ],
)
def test_invalid_queries_return_422(url):
    assert client.get(url).status_code == 422


def test_csv_export_is_explicitly_mock_and_preserves_source_columns():
    response = client.get("/export?format=csv")
    assert response.status_code == 200
    assert "text/csv" in response.headers["content-type"]
    assert response.text.startswith("# Source: NASA")
    assert "source_file,source_row" in response.text
    assert len(response.text.splitlines()) == 2  # citation line + header; no invented rows


def test_chat_stream_is_parseable_and_abstains_without_evidence():
    response = client.post("/chat", json={"question": "Which materials are safe?"})
    assert response.status_code == 200
    assert "text/event-stream" in response.headers["content-type"]
    frames = response.text.strip().split("\n\n")
    models = {"progress": ProgressEvent, "answer": AnswerEvent, "done": DoneEvent}
    names = []
    for frame in frames:
        name, payload = frame.splitlines()
        event = name.removeprefix("event: ")
        data = json.loads(payload.removeprefix("data: "))
        models[event].model_validate(data)
        names.append(event)
        if event == "answer":
            assert data["status"] == "insufficient_evidence"
            assert data["citations"] == []
    assert names == ["progress", "answer", "done"]


@pytest.mark.parametrize("question", ["", "   ", "x" * 2001])
def test_invalid_chat_questions(question):
    assert client.post("/chat", json={"question": question}).status_code == 422


def test_supported_answer_requires_evidence():
    with pytest.raises(ValidationError):
        AnswerEvent(text="A physical conclusion", status="supported", citations=[])


def test_profiles_are_explicit_assumptions_and_weights_sum_to_one():
    config = load_profiles()
    assert sum(config.weights.model_dump().values()) == pytest.approx(1)
    assert {profile.id for profile in config.profiles} == {
        "earth",
        "iss",
        "moon_base",
        "rover",
        "spacesuit",
        "custom",
    }
    assert all(p.status == "illustrative" for p in config.profiles)
    rover = next(p for p in config.profiles if p.id == "rover")
    assert rover.oxygen.minimum == 0.30
    assert rover.pressure.maximum == pytest.approx(10.2 * 6.894757293168)
    assert config.weights.model_dump() == {
        "conditions": 0.4,
        "fuel_realism": 0.25,
        "safety_goal": 0.2,
        "data_richness": 0.15,
    }


def test_generated_contracts_and_web_fixtures_are_current():
    for path, expected in outputs().items():
        assert path.read_text() == expected, f"Regenerate {path.relative_to(ROOT)}"


def test_openapi_defines_all_routes_and_sse_payloads():
    schema = client.get("/openapi.json").json()
    assert {
        "/meta",
        "/investigations",
        "/investigations/{accession}",
        "/rank",
        "/tests",
        "/compare",
        "/export",
        "/chat",
    } <= set(schema["paths"])
    exported = json.loads((ROOT / "docs/contracts/openapi.json").read_text())
    assert exported == schema
    assert set(exported["paths"]["/chat"]["post"]["x-sse-events"]) == {"progress", "answer", "done"}


def test_complete_plan_custom_environment_and_safety_goal():
    response = client.get(
        "/rank?profile=custom&o2_fraction=0.34&pressure_kpa=70&flow_cm_s=10&gravity_level_g=0.1667&goal=suppression"
    )
    assert response.status_code == 200
    data = response.json()
    assert data["profile"]["oxygen"]["minimum"] == 0.34
    assert data["profile"]["gravity_level_g"] == 0.1667
    assert data["safety_goal"] == "suppression"
    assert set(data["items"][0]["breakdown"]) == {
        "conditions",
        "fuel_realism",
        "safety_goal",
        "data_richness",
    }
    assert all(item["score"] is None for item in data["items"])


@pytest.mark.parametrize(
    "query",
    [
        "profile=custom",
        "profile=custom&o2_fraction=0.34",
        "pressure_kpa=inf",
        "gravity_level_g=nan",
        "o2_fraction=0.3&oxygen_fraction=0.4",
        "goal=invalid",
    ],
)
def test_custom_conditions_reject_missing_conflicting_or_nonfinite_values(query):
    assert client.get("/rank?" + query).status_code == 422


def test_metadata_fixtures_expose_actual_retained_plan_fields():
    item = client.get("/investigations/PSI-26").json()
    assert item["doi"] == "10.60555/58h4-dy80"
    assert item["objectives"] and item["approach"] and item["hypothesis"]
    assert item["hardware"] and item["publications"] and item["file_count"] > 0
    assert item["summary"] is None  # no generated scientific interpretation
    header = client.get("/export?format=csv").text.splitlines()[1].split(",")
    assert {"test_date", "fuel", "sample_size_mm", "o2_fraction", "metrics", "doi"} <= set(header)
