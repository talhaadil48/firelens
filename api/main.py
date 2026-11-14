"""FireLens API. FIRELENS_MODE=snapshot serves a harvested PSI snapshot; mock serves fixtures.

Numbers come from code (rule 1): rankings, ranges, counts and rows are computed from the
snapshot. No PSI call in the request path except the cached hourly check behind /meta.
"""

import csv
import io
import json
import logging
import time
from collections.abc import Iterator
from typing import Annotated, Literal

from fastapi import Depends, FastAPI, HTTPException, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import Response, StreamingResponse

from api.config import Settings, load_profiles
from api.freshness import CatalogueCheck
from api.models import (
    MAX_TEST_PAGE,
    AnswerEvent,
    ChatRequest,
    CompareResponse,
    DoneEvent,
    ErrorResponse,
    ExperimentalTest,
    ExportResponse,
    Gravity,
    Investigation,
    InvestigationList,
    MetaResponse,
    ProfileConfig,
    ProgressEvent,
    RankResponse,
    ReviewStatus,
    TestList,
)
from api.rank import rank_all
from api.store import StoreManager, TestFilter

settings = Settings()
logging.basicConfig(
    level=settings.log_level, format="%(asctime)s %(levelname)s %(name)s %(message)s"
)
log = logging.getLogger("firelens.api")
DATA = StoreManager(settings.mode, settings.snapshot_dir, settings.pointer_check_seconds)
FRESHNESS = CatalogueCheck(
    settings.psi_check_seconds, enabled=settings.psi_check and settings.mode == "snapshot"
)

app = FastAPI(
    title="FireLens API",
    version="0.2.0",
    description=(
        "Ranks and explains NASA PSI microgravity combustion investigations for crewed-habitat "
        "fire safety. Every number is computed from a dated PSI snapshot."
    ),
    responses={404: {"model": ErrorResponse}},
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_methods=["GET", "POST"],
    allow_headers=["Content-Type"],
)


@app.middleware("http")
async def access_log(request: Request, call_next):
    started = time.perf_counter()
    response = await call_next(request)
    log.info(
        json.dumps(
            {
                "method": request.method,
                "path": request.url.path,
                "status": response.status_code,
                "ms": round((time.perf_counter() - started) * 1000, 1),
            }
        )
    )
    return response


def investigations() -> list[Investigation]:
    return DATA.store.investigations


def by_id(accession: str) -> Investigation:
    result = DATA.store.by_id.get(accession)
    if result is None:
        raise HTTPException(404, f"Unknown investigation: {accession}")
    return result


@app.get("/healthz", include_in_schema=False)
def healthz() -> dict:
    """Liveness/readiness probe for Azure Container Apps; no PSI or model call."""
    return {"status": "ok", "snapshot_id": DATA.store.snapshot_id}


@app.get("/meta", response_model=MetaResponse)
def meta() -> MetaResponse:
    store = DATA.store
    result = store.meta()
    checked_at, new = FRESHNESS.status(set(store.by_id))
    if checked_at is not None:
        result.catalogue_checked_at = checked_at
        result.new_releases_since_snapshot = len(new)
        result.new_release_accessions = new
    if store.mode == "snapshot" and result.reviewed_test_count == 0:
        result.warnings.append(
            "Column maps are awaiting review; test rows are shown as unreviewed."
        )
    return result


@app.get("/profiles", response_model=ProfileConfig)
def profiles() -> ProfileConfig:
    return load_profiles()


@app.get("/investigations", response_model=InvestigationList)
def list_investigations(
    q: str | None = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 100,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> InvestigationList:
    items = investigations()
    if q:
        needle = q.casefold()
        items = [
            i
            for i in items
            if needle
            in f"{i.title} {i.accession} {i.acronym or ''} {' '.join(i.keywords)}".casefold()
        ]
    return InvestigationList(
        items=items[offset : offset + limit],
        total=len(items),
        limit=limit,
        offset=offset,
        mode=DATA.store.mode,
    )


@app.get("/investigations/{accession}", response_model=Investigation)
def investigation(accession: str) -> Investigation:
    return by_id(accession)


@app.get("/rank", response_model=RankResponse)
def rank(
    profile: str = "iss",
    goal: Literal["prevention", "detection", "suppression"] | None = None,
    o2_fraction: Annotated[float | None, Query(ge=0, le=1)] = None,
    pressure_kpa: Annotated[float | None, Query(gt=0)] = None,
    flow_cm_s: Annotated[float | None, Query(ge=0)] = None,
) -> RankResponse:
    config = load_profiles()
    selected = next((p for p in config.profiles if p.id == profile), None)
    if selected is None:
        raise HTTPException(404, f"Unknown profile: {profile}")
    selected = selected.model_copy(deep=True)
    for name, value in [
        ("oxygen", o2_fraction),
        ("pressure", pressure_kpa),
        ("flow", flow_cm_s),
    ]:
        if value is not None:
            condition = getattr(selected, name)
            condition.minimum = condition.maximum = value
    store = DATA.store
    items = rank_all(
        store.investigations, store.tests, selected, goal, config, settings.allow_unreviewed
    )
    warnings = ["Profiles, weights and tolerances are illustrative and need scientific review."]
    if selected.gravity in (Gravity.REDUCED, Gravity.UNKNOWN):
        warnings.append(
            "PSI holds no partial-gravity data yet (LUCI and FM2 are future); "
            "microgravity and 1 g results can only bound it."
        )
    if store.mode == "mock":
        warnings.append("Mock fixtures: no normalized tests, so no score is calculated.")
    elif settings.allow_unreviewed:
        warnings.append("Includes rows from column maps that a person has not reviewed yet.")
    elif any(t.review_status != ReviewStatus.REVIEWED for t in store.tests):
        warnings.append(
            "Rows from unreviewed column maps are excluded; those investigations show as "
            "metadata only."
        )
    return RankResponse(
        profile=selected,
        goal=goal,
        weights=config.weights,
        items=items,
        mode=store.mode,
        warnings=warnings,
    )


def filter_params(
    accession: str | None = None,
    o2_min: Annotated[float | None, Query(ge=0, le=1)] = None,
    o2_max: Annotated[float | None, Query(ge=0, le=1)] = None,
    pressure_min: Annotated[float | None, Query(gt=0)] = None,
    pressure_max: Annotated[float | None, Query(gt=0)] = None,
    flow_min: Annotated[float | None, Query(ge=0)] = None,
    flow_max: Annotated[float | None, Query(ge=0)] = None,
    fuel_phase: Literal["solid", "liquid", "gas", "mixed", "unknown"] | None = None,
    outcome: Literal["ignited", "extinguished", "cool_flame", "failed", "unknown"] | None = None,
    reviewed_only: bool = False,
) -> TestFilter:
    if accession:
        by_id(accession)
    for lower, upper in [(o2_min, o2_max), (pressure_min, pressure_max), (flow_min, flow_max)]:
        if lower is not None and upper is not None and lower > upper:
            raise HTTPException(422, "Minimum filter cannot exceed maximum")
    return TestFilter(
        accession,
        o2_min,
        o2_max,
        pressure_min,
        pressure_max,
        flow_min,
        flow_max,
        fuel_phase,
        outcome,
        reviewed_only,
    )


@app.get("/tests", response_model=TestList)
def tests(
    flt: Annotated[TestFilter, Depends(filter_params)],
    limit: Annotated[int, Query(ge=1, le=MAX_TEST_PAGE)] = MAX_TEST_PAGE,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> TestList:
    rows = DATA.store.query_tests(flt)
    return TestList(
        items=rows[offset : offset + limit],
        total=len(rows),
        limit=limit,
        offset=offset,
        mode=DATA.store.mode,
    )


def parse_ids(ids: str) -> list[Investigation]:
    accessions = [accession.strip() for accession in ids.split(",")]
    if len(accessions) not in (2, 3) or len(set(accessions)) != len(accessions):
        raise HTTPException(422, "Supply 2–3 distinct investigation IDs, separated by commas")
    return [by_id(accession) for accession in accessions]


def describe_range(item: Investigation, field: str) -> str:
    found = item.condition_ranges.get(field)
    if found is None or found.minimum is None:
        return "not reported"
    if field == "o2_fraction":
        return f"{found.minimum * 100:.1f}–{found.maximum * 100:.1f} % O2"
    return f"{found.minimum:.4g}–{found.maximum:.4g} {found.unit}"


COMPARE_FIELDS = {
    "Fuel phase": lambda i: i.fuel_phase,
    "Platform": lambda i: i.platform or "not reported",
    "Research sub-area": lambda i: i.sub_area or "not reported",
    "Hardware": lambda i: "; ".join(i.hardware) or "not reported",
    "Fire-safety category": lambda i: ", ".join(i.fire_safety_tags) or "none tagged",
    "Oxygen tested": lambda i: describe_range(i, "o2_fraction"),
    "Pressure tested": lambda i: describe_range(i, "pressure_kpa"),
    "Airflow tested": lambda i: describe_range(i, "flow_cm_s"),
    "Normalized tests": lambda i: str(i.test_count),
    "Data status": lambda i: i.data_status,
}


@app.get("/compare", response_model=CompareResponse)
def compare(ids: str) -> CompareResponse:
    items = parse_ids(ids)
    same, different = [], []
    for label, getter in COMPARE_FIELDS.items():
        values = [getter(item) for item in items]
        if len(set(values)) == 1:
            same.append(f"{label}: {values[0]}")
        else:
            different.append(
                f"{label}: "
                + "; ".join(
                    f"{item.acronym or item.accession} {value}"
                    for item, value in zip(items, values, strict=True)
                )
            )
    names = ", ".join(item.acronym or item.accession for item in items)
    return CompareResponse(
        investigations=items,
        same=same,
        different=different,
        summary=(
            f"{names}: {len(same)} attributes match and {len(different)} differ, compared "
            "field by field from the snapshot records."
        ),
        warnings=[
            "Different investigations do not imply directly comparable materials or conditions."
        ],
        mode=DATA.store.mode,
    )


CSV_FIELDS = [
    "test_id",
    "accession",
    "investigation",
    "test_date",
    "fuel",
    "fuel_phase",
    "sample_geometry",
    "sample_size_mm",
    "o2_fraction",
    "pressure_kpa",
    "diluent",
    "flow_cm_s",
    "flow_direction",
    "outcome",
    "doi",
    "review_status",
    "source_url",
    "source_version",
    "source_file",
    "source_row",
]


def csv_value(row: ExperimentalTest, field: str):
    if field.startswith("source_"):
        value = getattr(row.provenance, field)
    else:
        value = getattr(row, field)
    if value is None:
        return ""  # missing stays empty, never zero
    return getattr(value, "value", value)


@app.get(
    "/export",
    response_model=ExportResponse,
    responses={200: {"content": {"text/csv": {"schema": {"type": "string"}}}}},
)
def export(
    flt: Annotated[TestFilter, Depends(filter_params)],
    format: Annotated[str, Query(pattern=r"^(csv|json)$")] = "csv",
) -> Response | ExportResponse:
    store = DATA.store
    rows = store.query_tests(flt)
    accessions = sorted({r.accession for r in rows}, key=lambda a: int(a.split("-")[1]))
    cited = [store.by_id[a] for a in accessions if a in store.by_id]
    credit = (
        f"NASA Physical Sciences Informatics (CC0-1.0); FireLens {store.mode} {store.snapshot_id}"
    )
    if format == "json":
        return ExportResponse(
            source_credit=credit,
            mode=store.mode,
            tests=rows,
            investigations=cited or store.investigations,
        )
    stream = io.StringIO(newline="")
    stream.write(f"# Source: {credit}\r\n")
    if cited:
        stream.write(
            "# Cite: "
            + "; ".join(f"{i.accession} {i.acronym or ''} doi:{i.doi} v{i.version}" for i in cited)
            + "\r\n"
        )
    if any(r.review_status != ReviewStatus.REVIEWED for r in rows):
        stream.write("# Rows marked unreviewed come from column maps not yet approved.\r\n")
    writer = csv.writer(stream)
    writer.writerow(CSV_FIELDS)
    for row in rows:
        writer.writerow([csv_value(row, field) for field in CSV_FIELDS])
    return Response(
        stream.getvalue(),
        media_type="text/csv",
        headers={
            "Content-Disposition": f'attachment; filename="firelens-tests-{store.snapshot_id}.csv"',
        },
    )


def sse(event: str, payload: dict) -> str:
    return f"event: {event}\ndata: {json.dumps(payload, ensure_ascii=False)}\n\n"


@app.post(
    "/chat",
    response_class=StreamingResponse,
    responses={
        200: {
            "description": (
                "SSE: progress, answer, done. See docs/contracts/sse.md for event payloads."
            ),
            "content": {"text/event-stream": {"schema": {"type": "string"}}},
        }
    },
)
def chat(request: ChatRequest) -> StreamingResponse:
    for accession in request.investigation_ids:
        by_id(accession)

    def events() -> Iterator[str]:
        yield sse(
            "progress",
            ProgressEvent(
                stage="retrieval", message="Offline contract mock; no LLM called."
            ).model_dump(),
        )
        yield sse(
            "answer",
            AnswerEvent(
                text=(
                    "Insufficient evidence: Phase 2 contains catalogue metadata, "
                    "not reviewed experimental findings."
                ),
                status="insufficient_evidence",
                citations=[],
            ).model_dump(mode="json"),
        )
        yield sse("done", DoneEvent(finish_reason="insufficient_evidence").model_dump())

    return StreamingResponse(
        events(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )


# Serve the same SSE payload definitions in /openapi.json that web types use.
_default_openapi = app.openapi


def openapi_with_events() -> dict:
    schema = _default_openapi()
    for model in [ProgressEvent, AnswerEvent, DoneEvent]:
        fragment = model.model_json_schema(ref_template="#/components/schemas/{model}")
        definitions = fragment.pop("$defs", {})
        schema["components"]["schemas"].update(definitions)
        schema["components"]["schemas"][model.__name__] = fragment
    schema["paths"]["/chat"]["post"]["x-sse-events"] = {
        "progress": {"$ref": "#/components/schemas/ProgressEvent"},
        "answer": {"$ref": "#/components/schemas/AnswerEvent"},
        "done": {"$ref": "#/components/schemas/DoneEvent"},
    }
    return schema


app.openapi = openapi_with_events
