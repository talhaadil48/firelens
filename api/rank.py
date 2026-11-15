"""Mission-profile relevance ranking: R = 0.40*C + 0.25*F + 0.20*M + 0.15*D."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

import duckdb
from fastapi import HTTPException

from api.config import load_profiles
from api.models import (
    Gravity,
    Investigation,
    MissionProfile,
    ProfileConfig,
    RankItem,
    RankResponse,
)
from api.snapshot import LoadedSnapshot

_FUEL_PHASE_REALISM: dict[str, float] = {
    "solid": 1.0,
    "mixed": 0.80,
    "liquid": 0.60,
    "gas": 0.35,
    "unknown": 0.25,
}

_OXYGEN_POINT_TOLERANCE = 0.03
_PRESSURE_POINT_TOLERANCE_KPA = 10.0
_FLOW_POINT_TOLERANCE_CM_S = 5.0


@dataclass(frozen=True)
class _ConditionBounds:
    o2_min: float
    o2_max: float
    pressure_min: float
    pressure_max: float
    flow_active: bool
    flow_min: float | None
    flow_max: float | None


@dataclass(frozen=True)
class _InvestigationSqlStats:
    total_rows: int = 0
    measurement_rows: int = 0
    o2_p_rows: int = 0
    valid_rows: int = 0
    matching_rows: int = 0
    matching_o2: int = 0
    matching_p: int = 0
    matching_flow: int = 0
    reduced_g_rows: int = 0
    has_analysis: bool = False
    fuel_realism_avg: float | None = None


def resolve_profile(
    *,
    profile: str = "iss",
    oxygen_fraction: float | None = None,
    o2_fraction: float | None = None,
    pressure_kpa: float | None = None,
    flow_cm_s: float | None = None,
    gravity_level_g: float | None = None,
) -> tuple[ProfileConfig, MissionProfile]:
    """Validate query parameters and return (ProfileConfig, configured MissionProfile)."""
    if oxygen_fraction is not None and o2_fraction is not None and oxygen_fraction != o2_fraction:
        raise HTTPException(422, "Conflicting oxygen_fraction and o2_fraction inputs")
    oxygen = o2_fraction if o2_fraction is not None else oxygen_fraction
    if profile == "custom" and (oxygen is None or pressure_kpa is None):
        raise HTTPException(422, "Custom profiles require o2_fraction and pressure_kpa")
    config = load_profiles()
    selected = next((p for p in config.profiles if p.id == profile), None)
    if selected is None:
        raise HTTPException(404, f"Unknown profile: {profile}")
    selected = selected.model_copy(deep=True)
    for name, value in [("oxygen", oxygen), ("pressure", pressure_kpa), ("flow", flow_cm_s)]:
        if value is not None:
            condition = getattr(selected, name)
            condition.minimum = condition.maximum = value
    if gravity_level_g is not None:
        selected.gravity_level_g = gravity_level_g
        selected.gravity = (
            Gravity.NORMAL
            if gravity_level_g == 1
            else Gravity.MICROGRAVITY
            if gravity_level_g == 0
            else Gravity.REDUCED
        )
        selected.assumptions.append("Gravity level was explicitly supplied by the user.")
    return config, selected


def _profile_bounds(profile: MissionProfile) -> _ConditionBounds:
    o2_lo = profile.oxygen.minimum
    o2_hi = profile.oxygen.maximum
    if o2_lo is not None and o2_hi is not None and o2_lo == o2_hi:
        o2_min = max(0.0, o2_lo - _OXYGEN_POINT_TOLERANCE)
        o2_max = min(1.0, o2_hi + _OXYGEN_POINT_TOLERANCE)
    else:
        o2_min = o2_lo if o2_lo is not None else 0.0
        o2_max = o2_hi if o2_hi is not None else 1.0

    p_lo = profile.pressure.minimum
    p_hi = profile.pressure.maximum
    if p_lo is not None and p_hi is not None and p_lo == p_hi:
        pressure_min = max(0.0, p_lo - _PRESSURE_POINT_TOLERANCE_KPA)
        pressure_max = p_hi + _PRESSURE_POINT_TOLERANCE_KPA
    else:
        pressure_min = p_lo if p_lo is not None else 0.0
        pressure_max = p_hi if p_hi is not None else 1e9

    f_lo = profile.flow.minimum
    f_hi = profile.flow.maximum
    flow_active = f_lo is not None or f_hi is not None
    if not flow_active:
        flow_min, flow_max = None, None
    elif f_lo is not None and f_hi is not None and f_lo == f_hi:
        flow_min = max(0.0, f_lo - _FLOW_POINT_TOLERANCE_CM_S)
        flow_max = f_hi + _FLOW_POINT_TOLERANCE_CM_S
    else:
        flow_min = f_lo if f_lo is not None else 0.0
        flow_max = f_hi if f_hi is not None else 1e9

    return _ConditionBounds(
        o2_min=o2_min,
        o2_max=o2_max,
        pressure_min=pressure_min,
        pressure_max=pressure_max,
        flow_active=flow_active,
        flow_min=flow_min,
        flow_max=flow_max,
    )


def _query_sql_stats(
    parquet_path: Path,
    bounds: _ConditionBounds,
) -> dict[str, _InvestigationSqlStats]:
    escaped = str(parquet_path).replace("'", "''")
    source = f"read_parquet('{escaped}')"

    measurement_cond = (
        "record_kind = 'individual_test' AND evidence_type = 'measurement' "
        "AND NOT COALESCE(CAST(json_extract(provenance, '$.is_mock') AS BOOLEAN), FALSE)"
    )
    o2_p_cond = f"{measurement_cond} AND o2_fraction IS NOT NULL AND pressure_kpa IS NOT NULL"
    valid_cond = f"{o2_p_cond} AND flow_cm_s IS NOT NULL" if bounds.flow_active else o2_p_cond

    o2_match = "o2_fraction >= ? AND o2_fraction <= ?"
    p_match = "pressure_kpa >= ? AND pressure_kpa <= ?"
    if bounds.flow_active:
        flow_match_expr = "flow_cm_s >= ? AND flow_cm_s <= ?"
        full_match = f"({valid_cond}) AND ({o2_match}) AND ({p_match}) AND ({flow_match_expr})"
    else:
        flow_match_expr = "TRUE"
        full_match = f"({valid_cond}) AND ({o2_match}) AND ({p_match})"

    fuel_score_sql = (
        "CASE fuel_phase "
        "WHEN 'solid' THEN 1.0 "
        "WHEN 'mixed' THEN 0.80 "
        "WHEN 'liquid' THEN 0.60 "
        "WHEN 'gas' THEN 0.35 "
        "ELSE NULL END"
    )
    analysis_sql = (
        f"MAX(CASE WHEN ({valid_cond}) AND ("
        "(outcome IS NOT NULL AND outcome != 'unknown') OR "
        "(metrics IS NOT NULL AND TRIM(CAST(metrics AS VARCHAR)) NOT IN ('', '{}', 'null', 'NULL'))"
        ") THEN 1 ELSE 0 END)"
    )

    params: list[Any] = [bounds.o2_min, bounds.o2_max, bounds.pressure_min, bounds.pressure_max]
    if bounds.flow_active:
        params.extend([bounds.flow_min, bounds.flow_max])
    params.extend([bounds.o2_min, bounds.o2_max, bounds.pressure_min, bounds.pressure_max])
    if bounds.flow_active:
        params.extend([bounds.flow_min, bounds.flow_max])

    sql = f"""
        SELECT
            accession,
            COUNT(*) AS total_rows,
            SUM(CASE WHEN {measurement_cond} THEN 1 ELSE 0 END) AS measurement_rows,
            SUM(CASE WHEN {o2_p_cond} THEN 1 ELSE 0 END) AS o2_p_rows,
            SUM(CASE WHEN {valid_cond} THEN 1 ELSE 0 END) AS valid_rows,
            SUM(CASE WHEN {full_match} THEN 1 ELSE 0 END) AS matching_rows,
            SUM(CASE WHEN ({valid_cond}) AND ({o2_match}) THEN 1 ELSE 0 END) AS matching_o2,
            SUM(CASE WHEN ({valid_cond}) AND ({p_match}) THEN 1 ELSE 0 END) AS matching_p,
            SUM(
                CASE WHEN ({valid_cond}) AND ({flow_match_expr}) THEN 1 ELSE 0 END
            ) AS matching_flow,
            SUM(CASE WHEN ({valid_cond}) AND (
                gravity = 'reduced_gravity' OR
                (gravity_level_g IS NOT NULL AND gravity_level_g > 0 AND gravity_level_g < 0.99)
            ) THEN 1 ELSE 0 END) AS reduced_g_rows,
            {analysis_sql} AS has_analysis,
            AVG(CASE WHEN ({valid_cond}) THEN {fuel_score_sql} ELSE NULL END) AS fuel_realism_avg
        FROM {source}
        GROUP BY accession
    """

    stats: dict[str, _InvestigationSqlStats] = {}
    with duckdb.connect(":memory:") as conn:
        for row in conn.execute(sql, params).fetchall():
            (
                accession,
                total_rows,
                measurement_rows,
                o2_p_rows,
                valid_rows,
                matching_rows,
                matching_o2,
                matching_p,
                matching_flow,
                reduced_g_rows,
                has_analysis,
                fuel_realism_avg,
            ) = row
            stats[str(accession)] = _InvestigationSqlStats(
                total_rows=int(total_rows or 0),
                measurement_rows=int(measurement_rows or 0),
                o2_p_rows=int(o2_p_rows or 0),
                valid_rows=int(valid_rows or 0),
                matching_rows=int(matching_rows or 0),
                matching_o2=int(matching_o2 or 0),
                matching_p=int(matching_p or 0),
                matching_flow=int(matching_flow or 0),
                reduced_g_rows=int(reduced_g_rows or 0),
                has_analysis=bool(has_analysis),
                fuel_realism_avg=float(fuel_realism_avg) if fuel_realism_avg is not None else None,
            )
    return stats


def _is_partial_gravity_requested(profile: MissionProfile) -> bool:
    if profile.gravity == Gravity.REDUCED:
        return True
    g = profile.gravity_level_g
    return g is not None and 0 < g < 0.99


def _score_investigation(
    inv: Investigation,
    stats: _InvestigationSqlStats,
    bounds: _ConditionBounds,
    profile: MissionProfile,
    goal: Literal["prevention", "detection", "suppression"],
    config: ProfileConfig,
) -> RankItem:
    weight_keys = list(config.weights.model_dump())
    partial_g_requested = _is_partial_gravity_requested(profile)

    if stats.valid_rows == 0:
        gaps: list[str] = []
        if stats.total_rows == 0:
            gaps.append("No normalized test rows in snapshot")
        elif stats.measurement_rows == 0:
            gaps.append(
                "Normalized test rows exist but are grouped, mock or non-measurement "
                "(excluded from scoring)"
            )
        elif bounds.flow_active and stats.o2_p_rows > 0:
            gaps.append("test rows are missing airflow (flow_cm_s) for the selected flow profile")
        else:
            gaps.append("test rows are missing required oxygen or pressure measurements")
        if partial_g_requested:
            gaps.append("No partial-gravity test rows in PSI snapshot")
        return RankItem(
            accession=inv.accession,
            score=None,
            breakdown={key: None for key in weight_keys},
            gaps=gaps,
            rationale=(
                "No normalized measurement rows satisfy the profile condition inputs; "
                "score remains null."
            ),
        )

    c_score = round(min(1.0, max(0.0, stats.matching_rows / stats.valid_rows)), 4)

    if stats.fuel_realism_avg is not None:
        f_score = round(min(1.0, max(0.0, stats.fuel_realism_avg)), 4)
    else:
        f_score = _FUEL_PHASE_REALISM.get(inv.fuel_phase, 0.25)

    if goal in inv.fire_safety_tags:
        m_score = 1.0
    elif inv.fire_safety_tags:
        m_score = 0.35
    else:
        m_score = 0.25

    row_score = min(0.50, 0.20 + 0.30 * min(1.0, stats.valid_rows / 50.0))
    doc_score = 0.25 if (inv.documents or inv.publications) else 0.0
    analysis_score = (0.15 if stats.has_analysis else 0.0) + (
        0.10 if (inv.summary or inv.findings) else 0.0
    )
    d_score = round(min(1.0, row_score + doc_score + analysis_score), 4)

    weights = config.weights
    total_score = round(
        min(
            1.0,
            max(
                0.0,
                weights.conditions * c_score
                + weights.fuel_realism * f_score
                + weights.safety_goal * m_score
                + weights.data_richness * d_score,
            ),
        ),
        4,
    )

    gaps = []
    if stats.matching_o2 == 0:
        gaps.append("No tests within target oxygen envelope")
    if stats.matching_p == 0:
        gaps.append("No tests within target pressure envelope")
    if bounds.flow_active and stats.matching_flow == 0:
        gaps.append("No tests within target airflow envelope")
    if partial_g_requested and stats.reduced_g_rows == 0:
        gaps.append("No partial-gravity test rows in PSI snapshot")
    if goal not in inv.fire_safety_tags:
        gaps.append(f"Investigation is not tagged for safety goal '{goal}'")

    rationale = (
        f"{stats.matching_rows}/{stats.valid_rows} measurement rows match target "
        f"conditions (C={c_score:.2f}, F={f_score:.2f}, M={m_score:.2f}, D={d_score:.2f})."
    )
    return RankItem(
        accession=inv.accession,
        score=total_score,
        breakdown={
            "conditions": c_score,
            "fuel_realism": f_score,
            "safety_goal": m_score,
            "data_richness": d_score,
        },
        gaps=gaps,
        rationale=rationale,
    )


def rank_investigations(
    *,
    investigations: list[Investigation],
    snapshot: LoadedSnapshot | None,
    mock_mode: bool,
    profile: str = "iss",
    oxygen_fraction: float | None = None,
    o2_fraction: float | None = None,
    pressure_kpa: float | None = None,
    flow_cm_s: float | None = None,
    gravity_level_g: float | None = None,
    goal: Literal["prevention", "detection", "suppression"] = "prevention",
) -> RankResponse:
    """Rank investigations for the chosen mission profile and safety goal."""
    config, selected = resolve_profile(
        profile=profile,
        oxygen_fraction=oxygen_fraction,
        o2_fraction=o2_fraction,
        pressure_kpa=pressure_kpa,
        flow_cm_s=flow_cm_s,
        gravity_level_g=gravity_level_g,
    )

    if mock_mode:
        return RankResponse(
            profile=selected,
            weights=config.weights,
            safety_goal=goal,
            items=[
                RankItem(
                    accession=inv.accession,
                    breakdown={name: None for name in config.weights.model_dump()},
                    gaps=["No normalized tests in Phase 2 fixture"],
                    rationale=(
                        "Metadata fixture only; no quantitative relevance score can be calculated."
                    ),
                )
                for inv in investigations
            ],
            warnings=[
                "No ranking calculated. Fixture order is not a ranking.",
                "Profiles are supplied-plan scenarios; C/F/M/D weights require science validation.",
            ],
        )

    bounds = _profile_bounds(selected)
    if snapshot is not None and snapshot.parquet_path is not None:
        sql_stats = _query_sql_stats(snapshot.parquet_path, bounds)
    else:
        sql_stats = {}

    items = [
        _score_investigation(
            inv,
            sql_stats.get(inv.accession, _InvestigationSqlStats()),
            bounds,
            selected,
            goal,
            config,
        )
        for inv in investigations
    ]
    items.sort(
        key=lambda item: (
            item.score is None,
            -(item.score if item.score is not None else -1.0),
            item.accession,
        )
    )

    warnings = [
        "Scores represent research relevance (0.40*C + 0.25*F + 0.20*M + 0.15*D), "
        "not mission-safety certification.",
    ]
    if _is_partial_gravity_requested(selected):
        warnings.append(
            "NASA PSI contains no partial-gravity test measurements yet; "
            "microgravity and 1g results bound rather than directly measure partial-g behavior."
        )
    if any(item.score is None for item in items):
        warnings.append("Investigations without normalized measurement rows retain score=null.")

    return RankResponse(
        profile=selected,
        weights=config.weights,
        safety_goal=goal,
        items=items,
        warnings=warnings,
    )
