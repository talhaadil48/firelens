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
    assert frame["oxygen_fraction"].isna().all()


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
    frame.loc[0, "oxygen_fraction"] = 21  # percent accidentally passed as fraction
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
        RankWeights(oxygen=0.9)


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
