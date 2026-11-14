from copy import deepcopy

import pandera.errors
import pytest
from pydantic import ValidationError

from api.models import ExperimentalTest, Investigation, RankWeights
from harvest.validation import TestFrame as FrameSchema
from harvest.validation import validate_tests


@pytest.fixture
def row():
    return {
        "test_id": "synthetic-unit-test-1",
        "accession": "PSI-69",
        "oxygen_fraction": 0.21,
        "pressure_kpa": 101.325,
        "flow_cm_s": None,
        "evidence_type": "mock",
        "provenance": {
            "source_url": "https://example.org/synthetic-unit-test.csv",
            "source_file": "synthetic-unit-test.csv",
            "source_version": "unit-test-only",
            "source_row": 2,
            "retrieved_at": "2026-11-14T00:00:00Z",
            "is_mock": True,
        },
    }


def test_missing_conditions_remain_null(row):
    row["oxygen_fraction"] = None
    row["pressure_kpa"] = None
    parsed = ExperimentalTest.model_validate(row)
    assert parsed.oxygen_fraction is None
    frame = validate_tests([parsed])
    assert frame["o2_fraction"].isna().all()


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("oxygen_fraction", -0.1),
        ("oxygen_fraction", 1.1),
        ("pressure_kpa", 0),
        ("flow_cm_s", -1),
        ("oxygen_fraction", float("nan")),
        ("pressure_kpa", float("inf")),
    ],
)
def test_invalid_physical_conditions_rejected(row, field, value):
    row[field] = value
    with pytest.raises(ValidationError):
        ExperimentalTest.model_validate(row)


def test_provenance_and_units_are_required(row):
    row["provenance"]["source_row"] = None
    with pytest.raises(ValidationError):
        ExperimentalTest.model_validate(row)
    row["provenance"]["source_row"] = 2
    row["outcome_value"] = 3
    with pytest.raises(ValidationError):
        ExperimentalTest.model_validate(row)


def test_no_duplicate_tests_within_investigation(row):
    parsed = ExperimentalTest.model_validate(row)
    with pytest.raises(pandera.errors.SchemaErrors):
        validate_tests([parsed, parsed])


def test_same_local_id_in_different_investigations_is_allowed(row):
    other = deepcopy(row)
    other["accession"] = "PSI-159"
    assert (
        len(
            validate_tests(
                [ExperimentalTest.model_validate(row), ExperimentalTest.model_validate(other)]
            )
        )
        == 2
    )


def test_pandera_independently_rejects_out_of_range_values(row):
    frame = validate_tests([ExperimentalTest.model_validate(row)])
    frame.loc[0, "o2_fraction"] = 21  # percent accidentally passed as fraction
    with pytest.raises(pandera.errors.SchemaErrors):
        FrameSchema.validate(frame, lazy=True)


def test_mock_row_cannot_be_reviewed_as_science(row):
    row["review_status"] = "reviewed"
    with pytest.raises(ValidationError):
        ExperimentalTest.model_validate(row)


def test_empty_table_validates_without_fake_rows():
    assert validate_tests([]).empty


def test_weights_must_sum_to_one():
    with pytest.raises(ValidationError):
        RankWeights(conditions=0.9)


def test_finding_cannot_reference_nonexistent_citation():
    with pytest.raises(ValidationError):
        Investigation(
            accession="PSI-69",
            title="Synthetic test",
            research_area="Combustion Science",
            version="1",
            source_url="https://example.org",
            retrieved_at="2026-11-14T00:00:00Z",
            findings=[
                {"claim": "unsupported", "evidence_type": "metadata", "citation_ids": ["missing"]}
            ],
        )


@pytest.mark.parametrize(
    ("minimum", "maximum", "unit"),
    [
        (0.5, 0.2, "fraction"),
        (0, 21, "fraction"),
        (0, 70, "kPa"),
        (-1, 2, "cm/s"),
    ],
)
def test_invalid_scenario_envelopes_rejected(minimum, maximum, unit):
    from api.models import ConditionRange

    with pytest.raises(ValidationError):
        ConditionRange(minimum=minimum, maximum=maximum, unit=unit)


def test_complete_plan_row_preserves_dates_multiple_metrics_and_provenance(row):
    row.update(
        investigation="Synthetic test only",
        test_date="2026-01-02",
        fuel="synthetic",
        sample_geometry="sphere",
        sample_size_mm=2,
        diluent="N2",
        diluent_fractions={"N2": 0.79},
        doi="10.0000/synthetic",
        metrics={"burn_time": {"value": 3, "unit": "s"}, "diameter": {"value": 2, "unit": "mm"}},
    )
    parsed = ExperimentalTest.model_validate(row)
    payload = parsed.model_dump(mode="json")
    assert payload["o2_fraction"] == 0.21 and "oxygen_fraction" not in payload
    assert payload["source_file"] == row["provenance"]["source_file"]
    assert payload["source_row"] == 2 and payload["test_date"] == "2026-01-02"
    frame = validate_tests([parsed])
    assert frame.iloc[0]["fuel"] == "synthetic"
    assert set(frame.iloc[0]["metrics"]) == {"burn_time", "diameter"}
    assert frame.iloc[0]["test_date"].date() == parsed.test_date
    assert frame.iloc[0]["provenance"]["is_mock"] is True


@pytest.mark.parametrize("field,value", [("source_row", 99), ("source_file", "other.csv")])
def test_flat_and_nested_source_locations_cannot_conflict(row, field, value):
    row[field] = value
    with pytest.raises(ValidationError):
        ExperimentalTest.model_validate(row)


def test_legacy_input_aliases_serialize_to_the_complete_plan(row):
    row.update(material="synthetic", geometry="sphere")
    payload = ExperimentalTest.model_validate(row).model_dump(mode="json")
    assert payload["fuel"] == "synthetic" and payload["sample_geometry"] == "sphere"
    assert "material" not in payload and "geometry" not in payload


def test_invalid_nested_measurements_and_compositions_rejected(row):
    row["metrics"] = {"time": {"value": float("nan"), "unit": "s"}}
    with pytest.raises(ValidationError):
        ExperimentalTest.model_validate(row)
    row["metrics"] = {}
    row["diluent_fractions"] = {"N2": 0.8, "He": 0.8}
    with pytest.raises(ValidationError):
        ExperimentalTest.model_validate(row)


def test_text_chunk_and_snapshot_pointer_contracts():
    from api.models import SnapshotPointer, TextChunk

    context_chunk = TextChunk(
        chunk_id="ctx-1",
        source_kind="context_page",
        source_file="apollo-1.txt",
        source_url="https://www.nasa.gov/history/apollo-1/",
        text="Apollo 1 context text.",
    )
    assert context_chunk.accession is None

    with pytest.raises(ValidationError):
        TextChunk(
            chunk_id="doc-1",
            source_kind="document",
            source_file="report.pdf",
            source_url="https://psi.nasa.gov/report.pdf",
            text="Report text without accession.",
        )

    pointer = SnapshotPointer(
        snapshot_id="20261115T020000Z",
        created_at="2026-11-15T02:00:00Z",
        path="snapshots/20261115T020000Z/",
        investigation_count=24,
        test_count=0,
        chunk_count=1,
        files=["tests.parquet", "investigations.json", "chunks.jsonl", "SNAPSHOT.md"],
    )
    assert pointer.schema_version == 1


def test_column_map_template_validates():
    import yaml

    from api.config import ROOT
    from harvest.maps_schema import ColumnMap

    raw = yaml.safe_load((ROOT / "harvest/maps/TEMPLATE.yaml").read_text())
    parsed = ColumnMap.model_validate(raw)
    assert parsed.accession == "PSI-69"
    assert parsed.review_status == "unreviewed"
