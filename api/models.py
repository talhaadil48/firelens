"""Shared Phase 2 contracts. Missing science values remain null, never guessed."""

from datetime import date, datetime
from enum import StrEnum
from typing import Annotated, Literal

from pydantic import AliasChoices, BaseModel, ConfigDict, Field, HttpUrl, model_validator

Accession = Annotated[str, Field(pattern=r"^PSI-\d+$")]
Fraction = Annotated[float, Field(ge=0, le=1, allow_inf_nan=False)]
NonNegative = Annotated[float, Field(ge=0, allow_inf_nan=False)]
Positive = Annotated[float, Field(gt=0, allow_inf_nan=False)]


class Model(BaseModel):
    model_config = ConfigDict(extra="forbid")


class EvidenceType(StrEnum):
    MEASUREMENT = "measurement"
    SIMULATION = "simulation"
    AUTHOR_INTERPRETATION = "author_interpretation"
    METADATA = "metadata"
    MOCK = "mock"


class Gravity(StrEnum):
    NORMAL = "normal_gravity"
    MICROGRAVITY = "microgravity"
    REDUCED = "reduced_gravity"
    SIMULATED = "simulated"
    UNKNOWN = "unknown"


class Provenance(Model):
    source_url: HttpUrl
    source_file: str = Field(min_length=1)
    source_version: str = Field(min_length=1)
    retrieved_at: datetime
    source_row: int | None = Field(default=None, ge=1, description="1-based CSV physical row")
    page: int | None = Field(default=None, ge=1, description="1-based PDF page")
    source_sha256: str | None = Field(default=None, pattern=r"^[a-f0-9]{64}$")
    is_mock: bool = False


class Citation(Model):
    id: str = Field(min_length=1)
    accession: Accession
    locator: str = Field(min_length=1)
    supporting_text: str = Field(min_length=1)
    provenance: Provenance


class Metric(Model):
    value: float | None = Field(default=None, allow_inf_nan=False)
    unit: str = Field(min_length=1, description="Use '1' for dimensionless values")
    source_column: str | None = None
    provenance: Provenance | None = None


class SourceCell(Model):
    column: str
    value: str
    column_index: int = Field(ge=1)


class ExperimentalTest(Model):
    accession: Accession
    investigation: str | None = None
    test_id: str = Field(min_length=1)
    record_kind: Literal[
        "individual_test", "grouped_summary", "session", "reference", "source_note"
    ] = "individual_test"
    source_cells: list[SourceCell] = Field(default_factory=list)
    test_date: date | None = None
    campaign_id: str | None = None
    fuel: str | None = Field(default=None, validation_alias=AliasChoices("fuel", "material"))
    fuel_phase: Literal["solid", "liquid", "gas", "mixed", "unknown"] = "unknown"
    sample_geometry: str | None = Field(
        default=None, validation_alias=AliasChoices("sample_geometry", "geometry")
    )
    sample_size_mm: Positive | None = None
    sample_dimensions_mm: dict[str, Positive] = Field(default_factory=dict)
    thickness_mm: Positive | None = None
    o2_fraction: Fraction | None = Field(
        default=None, validation_alias=AliasChoices("o2_fraction", "oxygen_fraction")
    )
    oxygen_basis: Literal["mole", "volume", "mass", "unknown"] = "unknown"
    pressure_kpa: Positive | None = None
    diluent: str | None = None
    diluent_fractions: dict[str, Fraction] = Field(default_factory=dict)
    flow_cm_s: NonNegative | None = None
    flow_direction: str | None = None
    gravity: Gravity = Gravity.UNKNOWN
    gravity_level_g: NonNegative | None = None
    platform: str | None = None
    outcome: Literal["ignited", "extinguished", "cool_flame", "failed", "unknown"] | None = None
    metrics: dict[str, Metric] = Field(default_factory=dict)
    # Retained as optional legacy fields; new data uses named metrics.
    outcome_value: float | None = Field(
        default=None, allow_inf_nan=False, json_schema_extra={"deprecated": True}
    )
    outcome_unit: str | None = Field(default=None, json_schema_extra={"deprecated": True})
    baseline_test_id: str | None = None
    source_file: str | None = Field(default=None, min_length=1)
    source_row: int | None = Field(default=None, ge=1)
    doi: str | None = None
    evidence_type: EvidenceType
    provenance: Provenance
    notes: list[str] = Field(default_factory=list)

    @property
    def material(self) -> str | None:
        return self.fuel

    @property
    def geometry(self) -> str | None:
        return self.sample_geometry

    @property
    def oxygen_fraction(self) -> float | None:
        return self.o2_fraction

    @model_validator(mode="after")
    def check_evidence(self) -> "ExperimentalTest":
        if self.provenance.source_row is None:
            raise ValueError("Experimental test requires the original source row")
        if self.source_file is not None and self.source_file != self.provenance.source_file:
            raise ValueError("Flat source_file conflicts with provenance")
        if self.source_row is not None and self.source_row != self.provenance.source_row:
            raise ValueError("Flat source_row conflicts with provenance")
        self.source_file = self.provenance.source_file
        self.source_row = self.provenance.source_row
        if sum(self.diluent_fractions.values()) > 1 + 1e-9:
            raise ValueError("Diluent fractions cannot sum to more than 1")
        if self.outcome_value is not None and not self.outcome_unit:
            raise ValueError("An outcome value needs its original unit")
        if self.evidence_type == EvidenceType.MOCK and not self.provenance.is_mock:
            raise ValueError("Mock evidence must carry is_mock=true")
        return self


class SourceDocument(Model):
    name: str
    url: HttpUrl
    media_type: str | None = None
    size_bytes: int | None = Field(default=None, ge=0)


class Finding(Model):
    claim: str
    evidence_type: EvidenceType
    citation_ids: list[str] = Field(min_length=1)
    uncertainty_label: Literal["not_assessed", "reported", "not_reported", "qualitative"] = (
        "not_assessed"
    )
    uncertainty_note: str | None = None


class Publication(Model):
    title: str
    authors: str | None = None
    doi: str | None = None
    url: HttpUrl | None = None


class InvestigationSummary(Model):
    objective: str
    fuels_and_geometry: str | None = None
    conditions_tested: str | None = None
    varied: str | None = None
    sensors: list[str] = Field(default_factory=list)
    findings: list[Finding] = Field(default_factory=list)


class Investigation(Model):
    accession: Accession
    title: str
    acronym: str | None = None
    research_area: str
    description: str | None = None
    objectives: str | None = None
    approach: str | None = None
    hypothesis: str | None = None
    research_impacts: str | None = None
    sub_area: str | None = None
    sensors: list[str] = Field(default_factory=list)
    measurements: list[str] = Field(default_factory=list)
    file_count: int | None = Field(default=None, ge=0)
    file_size_bytes: int | None = Field(default=None, ge=0)
    publications: list[Publication] = Field(default_factory=list)
    summary: InvestigationSummary | None = None
    doi: str | None = None
    version: str
    license: str | None = None
    source_url: HttpUrl
    retrieved_at: datetime
    hardware: list[str] = Field(default_factory=list)
    platform: str | None = None
    fuel_phase: Literal["solid", "liquid", "gas", "mixed", "unknown"] = "unknown"
    fire_safety_tags: list[Literal["prevention", "detection", "suppression"]] = Field(
        default_factory=list
    )
    condition_ranges: dict[str, "ConditionRange"] = Field(default_factory=dict)
    documents: list[SourceDocument] = Field(default_factory=list)
    related_investigations: list[Accession] = Field(default_factory=list)
    findings: list[Finding] = Field(default_factory=list)
    citations: list[Citation] = Field(default_factory=list)
    test_count: int = Field(default=0, ge=0)
    record_count: int = Field(default=0, ge=0)
    data_gaps: list[str] = Field(default_factory=list)
    data_status: Literal["metadata_only", "raw_downloaded", "normalized"] = "metadata_only"
    fixture: bool = True

    @model_validator(mode="after")
    def check_citations(self) -> "Investigation":
        known = {citation.id for citation in self.citations}
        for finding in self.findings + (self.summary.findings if self.summary else []):
            if not set(finding.citation_ids) <= known:
                raise ValueError("Finding refers to an unknown citation")
        return self


class InvestigationList(Model):
    items: list[Investigation]
    total: int = Field(ge=0)
    limit: int = Field(ge=1, le=100)
    offset: int = Field(ge=0)
    mode: Literal["mock"] = "mock"


class MetaResponse(Model):
    mode: Literal["mock"] = "mock"
    snapshot_id: str
    snapshot_date: datetime
    investigation_count: int = Field(ge=0)
    test_count: int = Field(ge=0)
    new_releases_since_snapshot: int | None = None
    catalogue_checked_at: datetime | None = None
    warnings: list[str]


class ConditionRange(Model):
    minimum: float | None = Field(default=None, allow_inf_nan=False)
    maximum: float | None = Field(default=None, allow_inf_nan=False)
    unit: Literal["fraction", "kPa", "cm/s"]

    @model_validator(mode="after")
    def ordered(self) -> "ConditionRange":
        if self.minimum is not None and self.maximum is not None and self.minimum > self.maximum:
            raise ValueError("Minimum cannot exceed maximum")
        for value in (self.minimum, self.maximum):
            if value is None:
                continue
            if self.unit == "fraction" and not 0 <= value <= 1:
                raise ValueError("Fraction range must be between 0 and 1")
            if self.unit == "kPa" and value <= 0:
                raise ValueError("Pressure range must be positive")
            if self.unit == "cm/s" and value < 0:
                raise ValueError("Flow range cannot be negative")
        return self


class MissionProfile(Model):
    id: str
    label: str
    status: Literal["illustrative"] = "illustrative"
    description: str
    oxygen: ConditionRange
    pressure: ConditionRange
    flow: ConditionRange
    gravity: Gravity
    gravity_level_g: NonNegative | None = None
    assumptions: list[str]

    @model_validator(mode="after")
    def correct_units(self) -> "MissionProfile":
        if (self.oxygen.unit, self.pressure.unit, self.flow.unit) != ("fraction", "kPa", "cm/s"):
            raise ValueError("Mission condition units must be fraction, kPa, cm/s")
        return self


class RankWeights(Model):
    conditions: Fraction = 0.40
    fuel_realism: Fraction = 0.25
    safety_goal: Fraction = 0.20
    data_richness: Fraction = 0.15

    @model_validator(mode="after")
    def normalized(self) -> "RankWeights":
        if abs(sum(self.model_dump().values()) - 1) > 1e-9:
            raise ValueError("Ranking weights must sum to 1")
        return self


class ProfileConfig(Model):
    schema_version: Literal[1] = 1
    score_label: Literal["research relevance"] = "research relevance"
    weights: RankWeights
    profiles: list[MissionProfile]
    missing_data_policy: str


class RankItem(Model):
    accession: Accession
    score: Fraction | None = None
    breakdown: dict[str, Fraction | None]
    gaps: list[str]
    rationale: str


class RankResponse(Model):
    safety_goal: Literal["prevention", "detection", "suppression"] = "prevention"
    profile: MissionProfile
    weights: RankWeights
    items: list[RankItem]
    score_label: Literal["research relevance"] = "research relevance"
    mode: Literal["mock"] = "mock"
    warnings: list[str]


class TestList(Model):
    items: list[ExperimentalTest]
    total: int = Field(ge=0)
    limit: int = Field(ge=1, le=100)
    offset: int = Field(ge=0)
    mode: Literal["mock"] = "mock"


class CompareResponse(Model):
    investigations: list[Investigation] = Field(min_length=2, max_length=3)
    same: list[str]
    different: list[str]
    summary: str
    warnings: list[str]
    mode: Literal["mock"] = "mock"


class ExportResponse(Model):
    format: Literal["json"] = "json"
    source_credit: str
    mode: Literal["mock"] = "mock"
    tests: list[ExperimentalTest]
    investigations: list[Investigation]


class ChatRequest(Model):
    question: str = Field(min_length=1, max_length=2000, pattern=r"\S")
    investigation_ids: list[Accession] = Field(default_factory=list, max_length=10)


class ProgressEvent(Model):
    stage: Literal["retrieval", "answer"]
    message: str


class AnswerEvent(Model):
    text: str
    status: Literal["supported", "insufficient_evidence"]
    mode: Literal["mock"] = "mock"
    citations: list[Citation]

    @model_validator(mode="after")
    def supported_requires_citations(self) -> "AnswerEvent":
        if self.status == "supported" and not self.citations:
            raise ValueError("Supported answers require citations")
        return self


class DoneEvent(Model):
    finish_reason: Literal["stop", "insufficient_evidence", "error"]


class ErrorResponse(Model):
    detail: str


class TextChunk(Model):
    """Schema for one line in chunks.jsonl (Phase 5 precompute -> Phase 6 RAG)."""

    chunk_id: str = Field(min_length=1)
    accession: Accession | None = None
    source_kind: Literal["investigation_field", "summary", "document", "context_page"]
    source_file: str = Field(min_length=1)
    source_url: HttpUrl
    source_version: str | None = None
    doi: str | None = None
    page: int | None = Field(default=None, ge=1, description="1-based PDF/DOCX page")
    field_name: str | None = None
    text: str = Field(min_length=1)
    token_count: int | None = Field(default=None, ge=1)
    sha256: str | None = Field(default=None, pattern=r"^[a-f0-9]{64}$")

    @model_validator(mode="after")
    def require_accession_for_investigation_sources(self) -> "TextChunk":
        if self.source_kind != "context_page" and self.accession is None:
            raise ValueError(f"{self.source_kind} chunks require an investigation accession")
        return self


class SnapshotPointer(Model):
    """Schema for snapshots/latest.json (Phase 5 snapshot -> Phase 6 API & Phase 12 sync)."""

    schema_version: Literal[1] = 1
    snapshot_id: str = Field(min_length=1)
    created_at: datetime
    path: str = Field(min_length=1)
    investigation_count: int = Field(ge=0)
    test_count: int = Field(ge=0)
    chunk_count: int = Field(ge=0)
    files: list[str] = Field(min_length=1)
