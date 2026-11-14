"""Phase 2 contract server. No live model, scientific ranking, or normalized data yet."""

import csv
import io
import json
from collections.abc import Iterator
from typing import Annotated

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import Response, StreamingResponse

from api.config import ROOT, Settings, load_profiles
from api.models import (
    AnswerEvent,
    ChatRequest,
    CompareResponse,
    DoneEvent,
    ErrorResponse,
    ExportResponse,
    Investigation,
    InvestigationList,
    MetaResponse,
    ProfileConfig,
    ProgressEvent,
    RankItem,
    RankResponse,
    TestList,
)

settings = Settings()
if settings.mode != "mock":
    raise RuntimeError("Only FIRELENS_MODE=mock is implemented in Phase 2")

app = FastAPI(
    title="FireLens contract API",
    version="0.1.0",
    description="Phase 2 offline fixtures. Real NASA metadata; no validated scientific outputs.",
    responses={404: {"model": ErrorResponse}},
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_methods=["GET", "POST"],
    allow_headers=["Content-Type"],
)
SAMPLE = ROOT / "snapshots/sample"


def investigations() -> list[Investigation]:
    payload = InvestigationList.model_validate_json((SAMPLE / "investigations.json").read_text())
    return payload.items


def by_id(accession: str) -> Investigation:
    result = next((item for item in investigations() if item.accession == accession), None)
    if result is None:
        raise HTTPException(404, f"Unknown investigation: {accession}")
    return result


@app.get("/meta", response_model=MetaResponse)
def meta() -> MetaResponse:
    return MetaResponse.model_validate_json((SAMPLE / "meta.json").read_text())


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
        items = [i for i in items if q.casefold() in f"{i.title} {i.accession}".casefold()]
    return InvestigationList(
        items=items[offset : offset + limit], total=len(items), limit=limit, offset=offset
    )


@app.get("/investigations/{accession}", response_model=Investigation)
def investigation(accession: str) -> Investigation:
    return by_id(accession)


@app.get("/rank", response_model=RankResponse)
def rank(
    profile: str = "iss",
    oxygen_fraction: Annotated[float | None, Query(ge=0, le=1)] = None,
    pressure_kpa: Annotated[float | None, Query(gt=0)] = None,
    flow_cm_s: Annotated[float | None, Query(ge=0)] = None,
) -> RankResponse:
    config = load_profiles()
    selected = next((p for p in config.profiles if p.id == profile), None)
    if selected is None:
        raise HTTPException(404, f"Unknown profile: {profile}")
    selected = selected.model_copy(deep=True)
    for name, value in [
        ("oxygen", oxygen_fraction),
        ("pressure", pressure_kpa),
        ("flow", flow_cm_s),
    ]:
        if value is not None:
            condition = getattr(selected, name)
            condition.minimum = condition.maximum = value
    return RankResponse(
        profile=selected,
        weights=config.weights,
        items=[
            RankItem(
                accession=i.accession,
                breakdown={name: None for name in config.weights.model_dump()},
                gaps=["No reviewed normalized tests in Phase 2 fixture"],
                rationale=(
                    "Metadata fixture only; no quantitative relevance score can be calculated."
                ),
            )
            for i in investigations()
        ],
        warnings=[
            "No ranking calculated. Fixture order is not a ranking.",
            "Profiles and weights are illustrative and require scientific review.",
        ],
    )


@app.get("/tests", response_model=TestList)
def tests(
    accession: str | None = None,
    oxygen_min: Annotated[float | None, Query(ge=0, le=1)] = None,
    oxygen_max: Annotated[float | None, Query(ge=0, le=1)] = None,
    pressure_min: Annotated[float | None, Query(gt=0)] = None,
    pressure_max: Annotated[float | None, Query(gt=0)] = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 100,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> TestList:
    if accession:
        by_id(accession)
    for lower, upper in [(oxygen_min, oxygen_max), (pressure_min, pressure_max)]:
        if lower is not None and upper is not None and lower > upper:
            raise HTTPException(422, "Minimum filter cannot exceed maximum")
    # No normalized measurements are fabricated to make an empty plot look populated.
    return TestList(items=[], total=0, limit=limit, offset=offset)


def parse_ids(ids: str) -> list[Investigation]:
    accessions = [accession.strip() for accession in ids.split(",")]
    if len(accessions) not in (2, 3) or len(set(accessions)) != len(accessions):
        raise HTTPException(422, "Supply 2–3 distinct investigation IDs, separated by commas")
    return [by_id(accession.strip()) for accession in accessions]


@app.get("/compare", response_model=CompareResponse)
def compare(ids: str) -> CompareResponse:
    items = parse_ids(ids)
    return CompareResponse(
        investigations=items,
        same=["All selected records are NASA PSI combustion metadata fixtures."],
        different=[f"{item.accession}: {item.title}" for item in items],
        summary=(
            "Titles and identifiers can be compared; experimental outcomes are not normalized yet."
        ),
        warnings=[
            "Different investigations do not imply directly comparable materials or conditions."
        ],
    )


CSV_FIELDS = [
    "test_id",
    "accession",
    "material",
    "oxygen_fraction",
    "pressure_kpa",
    "flow_cm_s",
    "outcome",
    "outcome_value",
    "outcome_unit",
    "source_url",
    "source_file",
    "source_row",
]


@app.get(
    "/export",
    response_model=ExportResponse,
    responses={200: {"content": {"text/csv": {"schema": {"type": "string"}}}}},
)
def export(
    format: Annotated[str, Query(pattern=r"^(csv|json)$")] = "csv",
) -> Response | ExportResponse:
    if format == "json":
        return ExportResponse(
            source_credit="NASA Physical Sciences Informatics; metadata fixtures",
            tests=[],
            investigations=investigations(),
        )
    stream = io.StringIO(newline="")
    stream.write(
        "# Source: NASA Physical Sciences Informatics; FireLens Phase 2 mock; no test rows\r\n"
    )
    csv.writer(stream).writerow(CSV_FIELDS)
    return Response(
        stream.getvalue(),
        media_type="text/csv",
        headers={
            "Content-Disposition": 'attachment; filename="firelens-tests-mock.csv"',
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
