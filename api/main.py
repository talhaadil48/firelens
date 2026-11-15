"""FireLens FastAPI service supporting mock contract mode and Phase 6 snapshot/RAG mode."""

from __future__ import annotations

import csv
import io
import json
import logging
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Annotated, Any, Literal

import anyio
import httpx
from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import Response, StreamingResponse

from api.config import ROOT, Settings, load_profiles
from api.llm import LLMClient
from api.models import (
    AnswerEvent,
    ChatRequest,
    CompareResponse,
    DoneEvent,
    ErrorResponse,
    ExperimentalTest,
    ExportResponse,
    Investigation,
    InvestigationList,
    MetaResponse,
    ProfileConfig,
    ProgressEvent,
    RankResponse,
    TestList,
)
from api.rag import RateLimiter, stream_chat_events
from api.rank import rank_investigations
from api.snapshot import BlobFetcher, LoadedSnapshot, SnapshotLoader

logger = logging.getLogger("firelens.api")

SAMPLE = ROOT / "snapshots/sample"

CSV_FIELDS = [
    "record_kind",
    "source_cells",
    "notes",
    "test_id",
    "accession",
    "investigation",
    "test_date",
    "fuel",
    "fuel_phase",
    "sample_geometry",
    "sample_size_mm",
    "sample_dimensions_mm",
    "o2_fraction",
    "oxygen_basis",
    "pressure_kpa",
    "diluent",
    "diluent_fractions",
    "flow_cm_s",
    "flow_direction",
    "gravity",
    "gravity_level_g",
    "outcome",
    "metrics",
    "outcome_value",
    "outcome_unit",
    "source_url",
    "source_file",
    "source_row",
    "doi",
]
CSV_FIELDS = list(dict.fromkeys([*CSV_FIELDS, *ExperimentalTest.model_fields, "source_version"]))

CatalogueFetcher = Callable[[], list[dict[str, Any]]]


@dataclass
class _FreshnessEntry:
    snapshot_id: str
    checked_mono: float
    checked_at: datetime
    new_releases: int | None
    warning: str | None = None


class CatalogueFreshnessCache:
    """Cached hourly PSI catalogue check comparing live PSI releases against snapshot records."""

    def __init__(
        self,
        settings: Settings,
        *,
        catalogue_fetcher: CatalogueFetcher | None = None,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.settings = settings
        self._fetcher = catalogue_fetcher
        self._clock = clock
        self._lock = threading.Lock()
        self._cached: _FreshnessEntry | None = None

    def _fetch_psi_hits(self) -> list[dict[str, Any]]:
        if self._fetcher is not None:
            return self._fetcher()
        url = f"{self.settings.psi_base_url.rstrip('/')}/geode-py/ws/repo/search"
        with httpx.Client(timeout=10.0, follow_redirects=True) as client:
            response = client.get(
                url,
                params={
                    "term": "combustion",
                    "source": "psi",
                    "type": "investigation",
                    "size": 100,
                },
            )
            response.raise_for_status()
            payload = response.json()
        return list(payload.get("hits", {}).get("hits", []))

    def check(self, snap: LoadedSnapshot) -> tuple[int | None, datetime | None, str | None]:
        if self._fetcher is None and not self.settings.enable_live_catalogue_check:
            return None, None, None

        now = self._clock()
        with self._lock:
            if (
                self._cached is not None
                and self._cached.snapshot_id == snap.snapshot_id
                and (now - self._cached.checked_mono) < self.settings.catalogue_cache_seconds
            ):
                return (
                    self._cached.new_releases,
                    self._cached.checked_at,
                    self._cached.warning,
                )

            try:
                hits = self._fetch_psi_hits()
                new_releases = 0
                for hit in hits:
                    source = hit.get("_source", hit) if isinstance(hit, dict) else {}
                    area = source.get("Research Area") or source.get("research_area")
                    if area is not None and area != "Combustion Science":
                        continue
                    accession = source.get("Accession") or source.get("accession") or hit.get("_id")
                    if not accession:
                        continue
                    existing = snap.investigations_by_id.get(str(accession))
                    if existing is None:
                        new_releases += 1
                        continue
                    live_version = source.get("Version") or source.get("version")
                    if live_version is not None and str(live_version) != existing.version:
                        new_releases += 1

                checked_at = datetime.now(UTC)
                self._cached = _FreshnessEntry(
                    snapshot_id=snap.snapshot_id,
                    checked_mono=now,
                    checked_at=checked_at,
                    new_releases=new_releases,
                )
                return new_releases, checked_at, None
            except Exception as exc:
                warning = f"PSI catalogue check failed ({type(exc).__name__}); using cached status."
                logger.warning("PSI catalogue check failed (%s)", type(exc).__name__)
                if self._cached is not None and self._cached.snapshot_id == snap.snapshot_id:
                    return self._cached.new_releases, self._cached.checked_at, warning
                return None, None, warning


class AppRuntime:
    """Mutable runtime container holding settings, snapshot loader, LLM, cache, and limiter."""

    def __init__(
        self,
        settings: Settings | None = None,
        *,
        blob_fetcher: BlobFetcher | None = None,
        openai_client: Any = None,
        catalogue_fetcher: CatalogueFetcher | None = None,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.settings = settings or Settings()
        self.blob_fetcher = blob_fetcher
        self.llm = LLMClient(self.settings, openai_client=openai_client)
        self.snapshot_loader = SnapshotLoader(
            self.settings,
            self.llm,
            clock=clock,
            blob_fetcher=blob_fetcher,
        )
        self.freshness_cache = CatalogueFreshnessCache(
            self.settings,
            catalogue_fetcher=catalogue_fetcher,
            clock=clock,
        )
        self.rate_limiter = RateLimiter(
            self.settings.chat_rate_limit_per_minute,
            clock=clock,
        )

    @property
    def is_mock_mode(self) -> bool:
        if self.settings.mode == "snapshot":
            return False
        if "mode" in self.settings.model_fields_set and self.settings.mode == "mock":
            return True
        if self.settings.mode == "auto" or "snapshots_dir" in self.settings.model_fields_set:
            has_snapshot = (
                (self.settings.snapshots_dir / "latest.json").exists()
                or bool(self.settings.azure_storage_account_url.strip())
                or self.blob_fetcher is not None
            )
            return not has_snapshot
        if bool(self.settings.azure_storage_account_url.strip()) or self.blob_fetcher is not None:
            return False
        return True


runtime = AppRuntime()


def configure_runtime(
    settings: Settings | None = None,
    *,
    blob_fetcher: BlobFetcher | None = None,
    openai_client: Any = None,
    catalogue_fetcher: CatalogueFetcher | None = None,
    clock: Callable[[], float] = time.monotonic,
) -> AppRuntime:
    """Reconfigure module runtime (primarily for tests and startup overrides)."""
    global runtime
    runtime = AppRuntime(
        settings=settings,
        blob_fetcher=blob_fetcher,
        openai_client=openai_client,
        catalogue_fetcher=catalogue_fetcher,
        clock=clock,
    )
    return runtime


app = FastAPI(
    title="FireLens contract API",
    version="0.1.0",
    description="Phase 2 offline fixtures. Real NASA metadata; no validated scientific outputs.",
    responses={404: {"model": ErrorResponse}},
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=runtime.settings.cors_origins,
    allow_methods=["GET", "POST"],
    allow_headers=["Content-Type"],
)


def _sample_investigations() -> list[Investigation]:
    payload = InvestigationList.model_validate_json(
        (SAMPLE / "investigations.json").read_text(encoding="utf-8")
    )
    return payload.items


def investigations() -> list[Investigation]:
    if runtime.is_mock_mode:
        return _sample_investigations()
    return runtime.snapshot_loader.get_snapshot().investigations


def by_id(accession: str) -> Investigation:
    if runtime.is_mock_mode:
        result = next(
            (item for item in _sample_investigations() if item.accession == accession),
            None,
        )
    else:
        result = runtime.snapshot_loader.get_snapshot().investigations_by_id.get(accession)
    if result is None:
        raise HTTPException(404, f"Unknown investigation: {accession}")
    return result


@app.get("/meta", response_model=MetaResponse)
def meta() -> MetaResponse:
    if runtime.is_mock_mode:
        return MetaResponse.model_validate_json((SAMPLE / "meta.json").read_text(encoding="utf-8"))

    snap = runtime.snapshot_loader.get_snapshot()
    new_releases, checked_at, warning = runtime.freshness_cache.check(snap)
    warnings = list(snap.warnings)
    if warning:
        warnings.append(warning)
    return MetaResponse(
        snapshot_id=snap.snapshot_id,
        snapshot_date=snap.snapshot_date,
        investigation_count=len(snap.investigations),
        test_count=snap.test_count,
        new_releases_since_snapshot=new_releases,
        catalogue_checked_at=checked_at,
        warnings=warnings,
    )


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
        q_folded = q.casefold()
        items = [
            i
            for i in items
            if q_folded
            in f"{i.title} {i.accession} {i.acronym or ''} {i.objectives or ''}".casefold()
        ]
    return InvestigationList(
        items=items[offset : offset + limit], total=len(items), limit=limit, offset=offset
    )


@app.get("/investigations/{accession}", response_model=Investigation)
def investigation(accession: str) -> Investigation:
    return by_id(accession)


@app.get("/rank", response_model=RankResponse)
def rank(
    profile: str = "iss",
    oxygen_fraction: Annotated[
        float | None, Query(ge=0, le=1, allow_inf_nan=False, deprecated=True)
    ] = None,
    o2_fraction: Annotated[float | None, Query(ge=0, le=1, allow_inf_nan=False)] = None,
    pressure_kpa: Annotated[float | None, Query(gt=0, allow_inf_nan=False)] = None,
    flow_cm_s: Annotated[float | None, Query(ge=0, allow_inf_nan=False)] = None,
    gravity_level_g: Annotated[float | None, Query(ge=0, allow_inf_nan=False)] = None,
    goal: Literal["prevention", "detection", "suppression"] = "prevention",
) -> RankResponse:
    if runtime.is_mock_mode:
        return rank_investigations(
            investigations=_sample_investigations(),
            snapshot=None,
            mock_mode=True,
            profile=profile,
            oxygen_fraction=oxygen_fraction,
            o2_fraction=o2_fraction,
            pressure_kpa=pressure_kpa,
            flow_cm_s=flow_cm_s,
            gravity_level_g=gravity_level_g,
            goal=goal,
        )

    snap = runtime.snapshot_loader.get_snapshot()
    return rank_investigations(
        investigations=snap.investigations,
        snapshot=snap,
        mock_mode=False,
        profile=profile,
        oxygen_fraction=oxygen_fraction,
        o2_fraction=o2_fraction,
        pressure_kpa=pressure_kpa,
        flow_cm_s=flow_cm_s,
        gravity_level_g=gravity_level_g,
        goal=goal,
    )


def _validate_test_filters(
    accession: str | None,
    oxygen_min: float | None,
    oxygen_max: float | None,
    pressure_min: float | None,
    pressure_max: float | None,
) -> None:
    if accession:
        by_id(accession)
    for lower, upper in [(oxygen_min, oxygen_max), (pressure_min, pressure_max)]:
        if lower is not None and upper is not None and lower > upper:
            raise HTTPException(422, "Minimum filter cannot exceed maximum")


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
    _validate_test_filters(accession, oxygen_min, oxygen_max, pressure_min, pressure_max)
    if runtime.is_mock_mode:
        # No normalized measurements are fabricated to make an empty plot look populated.
        return TestList(items=[], total=0, limit=limit, offset=offset)

    items, total = runtime.snapshot_loader.query_tests(
        accession=accession,
        oxygen_min=oxygen_min,
        oxygen_max=oxygen_max,
        pressure_min=pressure_min,
        pressure_max=pressure_max,
        limit=limit,
        offset=offset,
    )
    return TestList(items=items, total=total, limit=limit, offset=offset)


def parse_ids(ids: str) -> list[Investigation]:
    accessions = [accession.strip() for accession in ids.split(",")]
    if len(accessions) not in (2, 3) or len(set(accessions)) != len(accessions):
        raise HTTPException(422, "Supply 2–3 distinct investigation IDs, separated by commas")
    return [by_id(accession.strip()) for accession in accessions]


def _format_range(inv: Investigation, key: str) -> str:
    cr = inv.condition_ranges.get(key)
    if cr is None or (cr.minimum is None and cr.maximum is None):
        return "unspecified"
    lo = f"{cr.minimum:g}" if cr.minimum is not None else "?"
    hi = f"{cr.maximum:g}" if cr.maximum is not None else "?"
    return f"{lo}–{hi} {cr.unit}"


def _build_field_grounded_compare(items: list[Investigation]) -> CompareResponse:
    same: list[str] = []
    different: list[str] = []

    areas = {i.research_area for i in items}
    if len(areas) == 1:
        same.append(f"Research area: all are {next(iter(areas))}.")
    else:
        different.append(
            "Research area: " + "; ".join(f"{i.accession}={i.research_area}" for i in items)
        )

    platforms = {i.platform for i in items if i.platform}
    if len(platforms) == 1 and all(i.platform for i in items):
        same.append(f"Platform: all conducted on {next(iter(platforms))}.")
    elif any(i.platform for i in items):
        different.append(
            "Platform: " + "; ".join(f"{i.accession}={i.platform or 'unspecified'}" for i in items)
        )

    hw_sets = [set(i.hardware) for i in items]
    shared_hw = set.intersection(*hw_sets) if hw_sets else set()
    if shared_hw:
        same.append("Shared hardware: " + ", ".join(sorted(shared_hw)) + ".")
    if len({tuple(sorted(s)) for s in hw_sets}) > 1:
        different.append(
            "Hardware: "
            + "; ".join(
                f"{i.accession}={', '.join(i.hardware) if i.hardware else 'unspecified'}"
                for i in items
            )
        )

    phases = {i.fuel_phase for i in items}
    if len(phases) == 1:
        same.append(f"Fuel phase: all {next(iter(phases))}.")
    else:
        different.append("Fuel phase: " + "; ".join(f"{i.accession}={i.fuel_phase}" for i in items))

    tag_sets = [set(i.fire_safety_tags) for i in items]
    shared_tags = set.intersection(*tag_sets) if tag_sets else set()
    if shared_tags:
        same.append("Shared fire-safety tags: " + ", ".join(sorted(shared_tags)) + ".")
    if len({tuple(sorted(s)) for s in tag_sets}) > 1:
        different.append(
            "Fire-safety tags: "
            + "; ".join(
                f"{i.accession}={', '.join(i.fire_safety_tags) if i.fire_safety_tags else 'none'}"
                for i in items
            )
        )

    counts = {i.test_count for i in items}
    if len(counts) == 1:
        same.append(f"Normalized test count: all have {next(iter(counts))} rows.")
    else:
        different.append("Test count: " + "; ".join(f"{i.accession}={i.test_count}" for i in items))

    for cond_key, label in [
        ("oxygen", "Oxygen range"),
        ("pressure", "Pressure range"),
        ("flow", "Flow range"),
    ]:
        rendered = [f"{i.accession}={_format_range(i, cond_key)}" for i in items]
        values = {_format_range(i, cond_key) for i in items}
        if len(values) == 1 and next(iter(values)) != "unspecified":
            same.append(f"{label}: all cover {next(iter(values))}.")
        elif any(v != "unspecified" for v in values):
            different.append(f"{label}: " + "; ".join(rendered))

    different.append(
        "Titles and DOIs: "
        + "; ".join(f"{i.accession}: {i.title} (DOI: {i.doi or 'none'})" for i in items)
    )

    if not same:
        same.append("All compared records belong to the active NASA PSI snapshot.")

    acc_list = ", ".join(i.accession for i in items)
    summary_parts = [f"Field comparison for {acc_list}:"]
    if same:
        summary_parts.append("Shared attributes: " + " ".join(same))
    if different:
        summary_parts.append("Observed differences: " + "; ".join(different[:3]) + ".")
    return CompareResponse(
        investigations=items,
        same=same,
        different=different,
        summary=" ".join(summary_parts),
        warnings=[
            "Different investigations do not imply directly comparable materials or conditions."
        ],
    )


@app.get("/compare", response_model=CompareResponse)
def compare(ids: str) -> CompareResponse:
    items = parse_ids(ids)
    if runtime.is_mock_mode:
        return CompareResponse(
            investigations=items,
            same=["All selected records are NASA PSI combustion metadata fixtures."],
            different=[f"{item.accession}: {item.title}" for item in items],
            summary=(
                "Titles and identifiers can be compared; experimental outcomes are not "
                "normalized yet."
            ),
            warnings=[
                "Different investigations do not imply directly comparable materials or conditions."
            ],
        )
    return _build_field_grounded_compare(items)


def _parse_optional_float(
    raw: str | None,
    name: str,
    *,
    gt: float | None = None,
    ge: float | None = None,
    le: float | None = None,
) -> float | None:
    if raw is None or raw == "":
        return None
    try:
        value = float(raw)
    except ValueError as exc:
        raise HTTPException(422, f"Invalid float for {name}") from exc
    if gt is not None and not (value > gt):
        raise HTTPException(422, f"{name} must be > {gt}")
    if ge is not None and not (value >= ge):
        raise HTTPException(422, f"{name} must be >= {ge}")
    if le is not None and not (value <= le):
        raise HTTPException(422, f"{name} must be <= {le}")
    return value


def _serialize_csv_value(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, dict | list):
        return json.dumps(value, ensure_ascii=False) if value else ""
    return str(value)


def _row_to_csv_list(row: ExperimentalTest, inv_doi: str | None) -> list[str]:
    dumped = row.model_dump(mode="json")
    dumped["source_url"] = str(row.provenance.source_url)
    dumped["doi"] = dumped.get("doi") or inv_doi
    return [_serialize_csv_value(dumped.get(field)) for field in CSV_FIELDS]


@app.get(
    "/export",
    response_model=ExportResponse,
    responses={200: {"content": {"text/csv": {"schema": {"type": "string"}}}}},
)
def export(
    format: Annotated[str, Query(pattern=r"^(csv|json)$")] = "csv",
    request: Request = None,
) -> Response | ExportResponse:
    if runtime.is_mock_mode:
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

    params = request.query_params if request is not None else {}
    accession = params.get("accession") or None
    oxygen_min = _parse_optional_float(params.get("oxygen_min"), "oxygen_min", ge=0, le=1)
    oxygen_max = _parse_optional_float(params.get("oxygen_max"), "oxygen_max", ge=0, le=1)
    pressure_min = _parse_optional_float(params.get("pressure_min"), "pressure_min", gt=0)
    pressure_max = _parse_optional_float(params.get("pressure_max"), "pressure_max", gt=0)
    _validate_test_filters(accession, oxygen_min, oxygen_max, pressure_min, pressure_max)

    snap = runtime.snapshot_loader.get_snapshot()
    rows, _ = runtime.snapshot_loader.query_tests(
        accession=accession,
        oxygen_min=oxygen_min,
        oxygen_max=oxygen_max,
        pressure_min=pressure_min,
        pressure_max=pressure_max,
        limit=None,
        offset=0,
    )
    if accession is not None:
        exported_invs = [snap.investigations_by_id[accession]]
    elif rows:
        seen_acc = {row.accession for row in rows}
        exported_invs = [inv for inv in snap.investigations if inv.accession in seen_acc]
    else:
        exported_invs = list(snap.investigations)

    dois = sorted(
        {
            doi
            for doi in [
                *(row.doi for row in rows),
                *(inv.doi for inv in exported_invs),
            ]
            if doi
        }
    )
    doi_text = ", ".join(dois) if dois else "none recorded"
    citation_credit = (
        f"NASA Physical Sciences Informatics; Snapshot {snap.snapshot_id} "
        f"({snap.snapshot_date.date().isoformat()}); DOIs: {doi_text}"
    )

    if format == "json":
        return ExportResponse(
            source_credit=citation_credit,
            tests=rows,
            investigations=exported_invs,
        )

    stream = io.StringIO(newline="")
    stream.write(f"# Source: {citation_credit}\r\n")
    writer = csv.writer(stream)
    writer.writerow(CSV_FIELDS)
    for row in rows:
        inv = snap.investigations_by_id.get(row.accession)
        writer.writerow(_row_to_csv_list(row, inv.doi if inv else None))
    return Response(
        stream.getvalue(),
        media_type="text/csv",
        headers={
            "Content-Disposition": 'attachment; filename="firelens-tests.csv"',
        },
    )


def _client_ip(http_request: Request | None) -> str:
    if http_request is None:
        return "local-test"
    # Uvicorn may normalize the peer using explicitly trusted proxy addresses.
    # Never parse caller-controlled forwarding headers here.
    if http_request.client and http_request.client.host:
        return http_request.client.host
    return "unknown"


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
def chat(request: ChatRequest, http_request: Request = None) -> StreamingResponse:
    for accession in request.investigation_ids:
        by_id(accession)

    if not runtime.is_mock_mode:
        runtime.rate_limiter.check(_client_ip(http_request))

    cancelled = threading.Event()
    events = stream_chat_events(
        request,
        loader=runtime.snapshot_loader,
        llm=runtime.llm,
        mock_mode=runtime.is_mock_mode,
        cancelled=cancelled.is_set,
    )

    async def response_events():
        async with anyio.create_task_group() as tasks:

            async def watch_disconnect():
                while not cancelled.is_set():
                    if http_request is not None and await http_request.is_disconnected():
                        cancelled.set()
                        tasks.cancel_scope.cancel()
                        return
                    await anyio.sleep(0.1)

            tasks.start_soon(watch_disconnect)
            try:
                while not cancelled.is_set():
                    frame = await anyio.to_thread.run_sync(
                        lambda: next(events, None), abandon_on_cancel=True
                    )
                    if frame is None or cancelled.is_set():
                        break
                    yield frame
            finally:
                cancelled.set()
                tasks.cancel_scope.cancel()

    return StreamingResponse(
        response_events(),
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
