"""Shared contracts (v2, aligned with the project plan). Missing science values stay null."""

from datetime import date, datetime
from enum import StrEnum
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, HttpUrl, model_validator

Accession = Annotated[str, Field(pattern=r"^PSI-\d+$")]
Fraction = Annotated[float, Field(ge=0, le=1, allow_inf_nan=False)]
NonNegative = Annotated[float, Field(ge=0, allow_inf_nan=False)]
Positive = Annotated[float, Field(gt=0, allow_inf_nan=False)]
FuelPhase = Literal["solid", "liquid", "gas", "mixed", "unknown"]
FireSafetyTag = Literal["prevention", "detection", "suppression"]
# "mock" = Phase 2 contract fixtures; "snapshot" = a harvested, normalized PSI snapshot.
DataMode = Literal["mock", "snapshot"]


class Model(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ReviewStatus(StrEnum):
    UNREVIEWED = "unreviewed"
    REVIEWED = "reviewed"
    REJECTED = "rejected"


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


class Outcome(StrEnum):
    IGNITED = "ignited"
    EXTINGUISHED = "extinguished"
    COOL_FLAME = "cool_flame"
    FAILED = "failed"
    UNKNOWN = "unknown"


class FlowDirection(StrEnum):
    OPPOSED = "opposed"
    CONCURRENT = "concurrent"
    QUIESCENT = "quiescent"
    UNKNOWN = "unknown"


class Metric(Model):
    """A measured quantity kept in its original unit (burn time, extinction diameter, ...)."""

    value: float = Field(allow_inf_nan=False)
    unit: str = Field(min_length=1)


class ExperimentalTest(Model):
    """One row of the unified test schema (plan: Data pipeline, unified test schema)."""

    test_id: str = Field(min_length=1)
    accession: Accession
    investigation: str | None = Field(default=None, description="Acronym, e.g. FLEX")
    campaign_id: str | None = None
    test_date: date | None = None
    fuel: str | None = None
    fuel_phase: FuelPhase = "unknown"
    sample_geometry: str | None = None
    sample_size_mm: Positive | None = None
    o2_fraction: Fraction | None = None
    oxygen_basis: Literal["mole", "volume", "mass", "unknown"] = "unknown"
    pressure_kpa: Positive | None = None
    diluent: str | None = Field(default=None, description="As reported, e.g. N2, He, CO2")
    flow_cm_s: NonNegative | None = None
    flow_direction: FlowDirection = FlowDirection.UNKNOWN
    gravity: Gravity = Gravity.UNKNOWN
    platform: str | None = None
    outcome: Outcome = Outcome.UNKNOWN
    metrics: dict[str, Metric] = Field(default_factory=dict)
    doi: str | None = None
    baseline_test_id: str | None = None
    evidence_type: EvidenceType
    review_status: ReviewStatus = ReviewStatus.UNREVIEWED
    provenance: Provenance
    notes: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def check_evidence(self) -> "ExperimentalTest":
        if self.provenance.source_row is None:
            raise ValueError("Experimental test requires the original source row")
        if self.evidence_type == EvidenceType.MOCK and not self.provenance.is_mock:
            raise ValueError("Mock evidence must carry is_mock=true")
        if self.provenance.is_mock and self.review_status == ReviewStatus.REVIEWED:
            raise ValueError("Mock rows cannot be scientifically reviewed")
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
    review_status: ReviewStatus = ReviewStatus.UNREVIEWED
    uncertainty_label: Literal["not_assessed", "reported", "not_reported", "qualitative"] = (
        "not_assessed"
    )
    uncertainty_note: str | None = None


class InvestigationSummary(Model):
    """LLM-written from supplied facts only; every key finding cites (plan: SI layer 1)."""

    objective: str
    fuels_geometry: str | None = None
    conditions_tested: str | None = None
    what_varied: str | None = None
    sensors: str | None = None
    key_findings: list[Finding] = Field(default_factory=list, max_length=3)
    fire_safety_tags: list[FireSafetyTag] = Field(default_factory=list)
    review_status: ReviewStatus = ReviewStatus.UNREVIEWED


class Investigation(Model):
    accession: Accession
    title: str
    acronym: str | None = None
    research_area: str
    sub_area: str | None = None
    description: str | None = None
    objectives: str | None = None
    approach: str | None = None
    hypothesis: str | None = None
    research_impacts: str | None = None
    keywords: list[str] = Field(default_factory=list)
    publications: list[str] = Field(default_factory=list)
    doi: str | None = None
    version: str
    license: str | None = None
    source_url: HttpUrl
    retrieved_at: datetime
    hardware: list[str] = Field(default_factory=list)
    platform: str | None = None
    fuel_phase: FuelPhase = "unknown"
    fire_safety_tags: list[FireSafetyTag] = Field(default_factory=list)
    condition_ranges: dict[str, "ConditionRange"] = Field(default_factory=dict)
    documents: list[SourceDocument] = Field(default_factory=list)
    related_investigations: list[Accession] = Field(default_factory=list)
    findings: list[Finding] = Field(default_factory=list)
    summary: InvestigationSummary | None = None
    citations: list[Citation] = Field(default_factory=list)
    test_count: int = Field(default=0, ge=0)
    file_counts: dict[str, int] = Field(
        default_factory=dict, description="Manifest files per PSI folder (not downloaded)"
    )
    total_size_bytes: int | None = Field(default=None, ge=0)
    review_status: ReviewStatus = ReviewStatus.UNREVIEWED
    data_status: Literal["metadata_only", "raw_downloaded", "normalized", "reviewed"] = (
        "metadata_only"
    )
    fixture: bool = False

    @model_validator(mode="after")
    def check_citations(self) -> "Investigation":
        known = {citation.id for citation in self.citations}
        summary_findings = self.summary.key_findings if self.summary else []
        for finding in [*self.findings, *summary_findings]:
            if not set(finding.citation_ids) <= known:
                raise ValueError("Finding refers to an unknown citation")
        return self


class InvestigationList(Model):
    items: list[Investigation]
    total: int = Field(ge=0)
    limit: int = Field(ge=1, le=100)
    offset: int = Field(ge=0)
    mode: DataMode = "mock"


class MetaResponse(Model):
    mode: DataMode = "mock"
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


class ConditionPoint(Model):
    """A single readout for a profile, e.g. Moon base 34 % O2 / 70 kPa from the plan."""

    o2_fraction: Fraction | None = None
    pressure_kpa: Positive | None = None
    flow_cm_s: NonNegative | None = None


class MissionProfile(Model):
    id: str
    label: str
    status: Literal["illustrative"] = "illustrative"
    description: str
    oxygen: ConditionRange
    pressure: ConditionRange
    flow: ConditionRange
    gravity: Gravity
    nominal: ConditionPoint | None = None
    assumptions: list[str]

    @model_validator(mode="after")
    def correct_units(self) -> "MissionProfile":
        if (self.oxygen.unit, self.pressure.unit, self.flow.unit) != ("fraction", "kPa", "cm/s"):
            raise ValueError("Mission condition units must be fraction, kPa, cm/s")
        return self


class RankWeights(Model):
    """R = 0.40 C + 0.25 F + 0.20 M + 0.15 D (plan: SI layer 2)."""

    condition: Fraction = Field(0.40, description="C: share of tests near the profile")
    fuel: Fraction = Field(0.25, description="F: fuel realism for habitats")
    category: Fraction = Field(0.20, description="M: fire-safety category match to the goal")
    richness: Fraction = Field(0.15, description="D: data richness")

    @model_validator(mode="after")
    def normalized(self) -> "RankWeights":
        if abs(sum(self.model_dump().values()) - 1) > 1e-9:
            raise ValueError("Ranking weights must sum to 1")
        return self


class Tolerances(Model):
    """How far a test may sit outside a profile envelope and still count as near it (C)."""

    o2_fraction: NonNegative
    pressure_kpa: NonNegative
    flow_cm_s: NonNegative


class RichnessScale(Model):
    """D = row_share * min(1, log(rows+1)/log(full+1)) + documents_share * has_reports."""

    rows_for_full_score: int = Field(ge=1)
    row_share: Fraction
    documents_share: Fraction

    @model_validator(mode="after")
    def shares_sum_to_one(self) -> "RichnessScale":
        if abs(self.row_share + self.documents_share - 1) > 1e-9:
            raise ValueError("Richness shares must sum to 1")
        return self


class ProfileConfig(Model):
    schema_version: Literal[2] = 2
    score_label: Literal["research relevance"] = "research relevance"
    weights: RankWeights
    tolerances: Tolerances
    fuel_realism: dict[FuelPhase, Fraction] = Field(
        description="F per fuel phase; a phase missing here scores null, not zero"
    )
    richness: RichnessScale
    profiles: list[MissionProfile]
    missing_data_policy: str
    review_status: Literal["draft_requires_science_review"]


class RankItem(Model):
    accession: Accession
    score: Fraction | None = None
    breakdown: dict[Literal["condition", "fuel", "category", "richness"], Fraction | None]
    status: Literal["scored", "metadata_only"] = "metadata_only"
    test_count: int = Field(default=0, ge=0)
    tests_near_profile: int | None = Field(default=None, ge=0)
    gaps: list[str]
    rationale: str


class RankResponse(Model):
    profile: MissionProfile
    goal: FireSafetyTag | None = None
    weights: RankWeights
    items: list[RankItem]
    score_label: Literal["research relevance"] = "research relevance"
    mode: DataMode = "mock"
    warnings: list[str]


MAX_TEST_PAGE = 5000  # the coverage map draws every row in one request


class TestList(Model):
    items: list[ExperimentalTest]
    total: int = Field(ge=0)
    limit: int = Field(ge=1, le=MAX_TEST_PAGE)
    offset: int = Field(ge=0)
    mode: DataMode = "mock"


class CompareResponse(Model):
    investigations: list[Investigation] = Field(min_length=2, max_length=3)
    same: list[str]
    different: list[str]
    summary: str
    warnings: list[str]
    mode: DataMode = "mock"


class ExportResponse(Model):
    format: Literal["json"] = "json"
    source_credit: str
    mode: DataMode = "mock"
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
    mode: DataMode = "mock"
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
