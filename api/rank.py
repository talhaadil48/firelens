"""Research-relevance ranking: R = wC*C + wF*F + wM*M + wD*D (plan: SI layer, 2).

C  share of the investigation's assessable tests that lie inside the profile envelope
   widened by the configured tolerances. A test is assessable when it reports at least one
   condition the profile defines; each reported, defined condition must be inside.
F  fuel realism for habitats, by fuel phase (config); a phase not listed -> null.
M  1 when the investigation carries the requested fire-safety goal (or, with no goal,
   any fire-safety category), else 0. Tags are curated per investigation.
D  row_share * min(1, ln(rows+1)/ln(full+1)) + documents_share * (publications listed).
Any null term -> score null ("metadata_only"). Nothing is renormalized or zero-filled.
Numbers come from code; no model call.
"""

import math
from dataclasses import dataclass

from api.models import (
    ConditionRange,
    ExperimentalTest,
    Investigation,
    MissionProfile,
    ProfileConfig,
    RankItem,
    ReviewStatus,
)

DIMENSIONS = [  # (profile attribute, test field, tolerance field, label, unit)
    ("oxygen", "o2_fraction", "o2_fraction", "O2", "fraction"),
    ("pressure", "pressure_kpa", "pressure_kpa", "pressure", "kPa"),
    ("flow", "flow_cm_s", "flow_cm_s", "airflow", "cm/s"),
]


@dataclass
class Envelope:
    field: str
    label: str
    low: float | None  # widened by tolerance; None = unbounded
    high: float | None
    profile: ConditionRange

    def contains(self, value: float) -> bool:
        return (self.low is None or value >= self.low) and (self.high is None or value <= self.high)


def envelopes(profile: MissionProfile, config: ProfileConfig) -> list[Envelope]:
    result = []
    for attribute, field, tolerance_field, label, _unit in DIMENSIONS:
        condition: ConditionRange = getattr(profile, attribute)
        if condition.minimum is None and condition.maximum is None:
            continue
        tolerance = getattr(config.tolerances, tolerance_field)
        low = None if condition.minimum is None else condition.minimum - tolerance
        high = None if condition.maximum is None else condition.maximum + tolerance
        result.append(Envelope(field, label, low, high, condition))
    return result


def fmt(value: float, field: str) -> str:
    if field == "o2_fraction":
        return f"{value * 100:.1f} % O2"
    return f"{value:.1f} kPa" if field == "pressure_kpa" else f"{value:.1f} cm/s"


def condition_term(
    rows: list[ExperimentalTest], boxes: list[Envelope]
) -> tuple[float | None, int, int]:
    assessable = near = 0
    for row in rows:
        compared = [(box, getattr(row, box.field)) for box in boxes]
        compared = [(box, value) for box, value in compared if value is not None]
        if not compared:
            continue
        assessable += 1
        near += all(box.contains(value) for box, value in compared)
    return (near / assessable if assessable else None), near, assessable


def coverage_gaps(inv: Investigation, boxes: list[Envelope]) -> list[str]:
    """Where the investigation's tested conditions stop short of the profile envelope."""
    gaps = []
    for box in boxes:
        tested = inv.condition_ranges.get(box.field)
        if tested is None:
            gaps.append(f"No tests report {box.label}")
            continue
        # Judged against the tolerance-widened envelope, so 70.2 kPa vs a 70 kPa cap is no gap.
        target_min, target_max = box.profile.minimum, box.profile.maximum
        if box.low is not None and tested.maximum is not None and tested.maximum < box.low:
            gaps.append(
                f"Highest tested {box.label} ({fmt(tested.maximum, box.field)}) is below "
                f"the profile minimum ({fmt(target_min, box.field)})"
            )
        if box.high is not None and tested.minimum is not None and tested.minimum > box.high:
            gaps.append(
                f"Lowest tested {box.label} ({fmt(tested.minimum, box.field)}) is above "
                f"the profile maximum ({fmt(target_max, box.field)})"
            )
    return gaps


def category_reason(goal: str | None, tags: list[str]) -> str:
    if goal:
        return f"tagged {goal}" if goal in tags else f"not tagged {goal}"
    return "fire-safety tags: " + ", ".join(tags) if tags else "no fire-safety tag"


def richness_term(inv: Investigation, rows: int, config: ProfileConfig) -> float:
    scale = config.richness
    row_part = min(1.0, math.log(rows + 1) / math.log(scale.rows_for_full_score + 1))
    documents = 1.0 if inv.publications else 0.0
    return scale.row_share * row_part + scale.documents_share * documents


def rank_one(
    inv: Investigation,
    rows: list[ExperimentalTest],
    profile: MissionProfile,
    goal: str | None,
    config: ProfileConfig,
    allow_unreviewed: bool,
) -> RankItem:
    usable = [
        r
        for r in rows
        if r.evidence_type == "measurement"
        and not r.provenance.is_mock
        and (allow_unreviewed or r.review_status == ReviewStatus.REVIEWED)
    ]
    boxes = envelopes(profile, config)
    gaps: list[str] = []
    if not boxes:
        condition, near, assessable = None, 0, 0
        gaps.append("Profile defines no conditions; set O2, pressure or airflow")
    else:
        condition, near, assessable = condition_term(usable, boxes)
        gaps += coverage_gaps(inv, boxes)
    if rows and not usable:
        gaps.append("Column map not reviewed yet: rows excluded from scoring")
    elif not rows:
        gaps.append("No normalized test table in this snapshot")
    fuel = config.fuel_realism.get(inv.fuel_phase)
    if fuel is None:
        gaps.append(f"Fuel phase '{inv.fuel_phase}' has no realism score")
    tags = inv.fire_safety_tags
    category = float(goal in tags) if goal else float(bool(tags))
    richness = richness_term(inv, len(rows), config)
    breakdown = {"condition": condition, "fuel": fuel, "category": category, "richness": richness}
    w = config.weights
    score = None
    if None not in breakdown.values():
        score = round(
            w.condition * condition + w.fuel * fuel + w.category * category + w.richness * richness,
            4,
        )
        score = min(1.0, score)
    rationale_parts = [
        f"C: {near} of {assessable} assessable tests inside the profile envelope"
        if condition is not None
        else "C: no assessable tests",
        f"F: {inv.fuel_phase} fuel" + (f" ({fuel:g})" if fuel is not None else " (unscored)"),
        "M: " + category_reason(goal, tags),
        f"D: {len(rows)} normalized rows"
        + (", publications listed" if inv.publications else ", no publications listed"),
    ]
    return RankItem(
        accession=inv.accession,
        score=score,
        breakdown={k: (None if v is None else round(v, 4)) for k, v in breakdown.items()},
        status="scored" if score is not None else "metadata_only",
        test_count=len(rows),
        tests_near_profile=near if condition is not None else None,
        gaps=gaps,
        rationale="; ".join(rationale_parts) + ".",
    )


def rank_all(
    investigations: list[Investigation],
    tests: list[ExperimentalTest],
    profile: MissionProfile,
    goal: str | None,
    config: ProfileConfig,
    allow_unreviewed: bool,
) -> list[RankItem]:
    by_accession: dict[str, list[ExperimentalTest]] = {}
    for row in tests:
        by_accession.setdefault(row.accession, []).append(row)
    items = [
        rank_one(inv, by_accession.get(inv.accession, []), profile, goal, config, allow_unreviewed)
        for inv in investigations
    ]
    # Scored first by score; unscored after, by data richness. Ties keep accession order.
    return sorted(
        items,
        key=lambda i: (i.score is None, -(i.score or 0), -(i.breakdown["richness"] or 0)),
    )
