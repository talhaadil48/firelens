"""Snapshot loader, DuckDB Parquet queries, and 15-minute pointer hot-swap."""

from __future__ import annotations

import json
import logging
import math
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

import duckdb
import httpx

from api.config import ROOT, Settings
from api.llm import LLMClient, SqlRowFilter, cosine_similarity
from api.models import (
    ExperimentalTest,
    Investigation,
    InvestigationList,
    Provenance,
    SnapshotPointer,
    TextChunk,
)

logger = logging.getLogger(__name__)

BlobFetcher = Callable[[str], bytes | None]

_PARQUET_COLUMNS: tuple[tuple[str, str], ...] = (
    ("test_id", "VARCHAR"),
    ("accession", "VARCHAR"),
    ("investigation", "VARCHAR"),
    ("test_date", "VARCHAR"),
    ("campaign_id", "VARCHAR"),
    ("fuel", "VARCHAR"),
    ("fuel_phase", "VARCHAR"),
    ("sample_geometry", "VARCHAR"),
    ("sample_size_mm", "DOUBLE"),
    ("sample_dimensions_mm", "VARCHAR"),
    ("thickness_mm", "DOUBLE"),
    ("o2_fraction", "DOUBLE"),
    ("oxygen_basis", "VARCHAR"),
    ("pressure_kpa", "DOUBLE"),
    ("diluent", "VARCHAR"),
    ("diluent_fractions", "VARCHAR"),
    ("flow_cm_s", "DOUBLE"),
    ("flow_direction", "VARCHAR"),
    ("gravity", "VARCHAR"),
    ("gravity_level_g", "DOUBLE"),
    ("platform", "VARCHAR"),
    ("outcome", "VARCHAR"),
    ("metrics", "VARCHAR"),
    ("outcome_value", "DOUBLE"),
    ("outcome_unit", "VARCHAR"),
    ("baseline_test_id", "VARCHAR"),
    ("source_file", "VARCHAR"),
    ("source_row", "BIGINT"),
    ("doi", "VARCHAR"),
    ("evidence_type", "VARCHAR"),
    ("review_status", "VARCHAR"),
    ("provenance", "VARCHAR"),
    ("notes", "VARCHAR"),
    ("source_url", "VARCHAR"),
    ("source_version", "VARCHAR"),
)

_JSON_DICT_FIELDS = frozenset(
    {"sample_dimensions_mm", "diluent_fractions", "metrics", "provenance"}
)
_JSON_LIST_FIELDS = frozenset({"notes"})


def _clean_scalar(value: Any) -> Any:
    if value is None:
        return None
    if isinstance(value, float) and math.isnan(value):
        return None
    return value


def _parse_json_field(value: Any, *, default: Any) -> Any:
    value = _clean_scalar(value)
    if value is None or value == "":
        return default
    if isinstance(value, str):
        return json.loads(value)
    return value


def write_tests_parquet(rows: list[ExperimentalTest], path: Path) -> None:
    """Write validated ExperimentalTest rows to Parquet via DuckDB without pandas."""
    path.parent.mkdir(parents=True, exist_ok=True)
    col_defs = ", ".join(f"{name} {dtype}" for name, dtype in _PARQUET_COLUMNS)
    placeholders = ", ".join("?" for _ in _PARQUET_COLUMNS)
    col_names = [name for name, _ in _PARQUET_COLUMNS]

    records: list[tuple[Any, ...]] = []
    for row in rows:
        dumped = row.model_dump(mode="json")
        dumped["source_url"] = str(row.provenance.source_url)
        dumped["source_version"] = row.provenance.source_version
        for field_name in _JSON_DICT_FIELDS | _JSON_LIST_FIELDS:
            dumped[field_name] = json.dumps(dumped[field_name], ensure_ascii=False)
        records.append(tuple(dumped.get(col) for col in col_names))

    escaped_path = str(path).replace("'", "''")
    with duckdb.connect(":memory:") as conn:
        conn.execute(f"CREATE TABLE tests ({col_defs})")
        if records:
            conn.executemany(f"INSERT INTO tests VALUES ({placeholders})", records)
        conn.execute(f"COPY tests TO '{escaped_path}' (FORMAT PARQUET)")


def row_from_duckdb_record(
    record: dict[str, Any],
    *,
    default_retrieved_at: datetime | None = None,
) -> ExperimentalTest:
    """Convert one DuckDB Parquet row dict into a validated ExperimentalTest."""
    cleaned: dict[str, Any] = {}
    for key, raw_value in record.items():
        value = _clean_scalar(raw_value)
        if key in _JSON_DICT_FIELDS:
            default_val = None if key == "provenance" else {}
            cleaned[key] = _parse_json_field(value, default=default_val)
        elif key in _JSON_LIST_FIELDS:
            cleaned[key] = _parse_json_field(value, default=[])
        elif key == "test_date":
            if isinstance(value, datetime):
                cleaned[key] = value.date()
            elif isinstance(value, date):
                cleaned[key] = value
            else:
                cleaned[key] = value
        else:
            cleaned[key] = value

    if not cleaned.get("provenance"):
        cleaned["provenance"] = Provenance(
            source_url=cleaned.get("source_url") or "https://psi.nasa.gov",
            source_file=cleaned.get("source_file") or "unknown.csv",
            source_version=cleaned.get("source_version") or "1",
            retrieved_at=default_retrieved_at or datetime.now(UTC),
            source_row=cleaned.get("source_row") or 1,
            is_mock=cleaned.get("evidence_type") == "mock",
        ).model_dump(mode="json")

    allowed = set(ExperimentalTest.model_fields)
    payload = {key: value for key, value in cleaned.items() if key in allowed}
    return ExperimentalTest.model_validate(payload)


def _parquet_sql_source(parquet_path: Path) -> str:
    escaped = str(parquet_path).replace("'", "''")
    return f"read_parquet('{escaped}')"


def _resolve_snapshot_dir(pointer: SnapshotPointer, snapshots_dir: Path) -> Path | None:
    pointer_path = Path(pointer.path)
    candidates = [
        pointer_path if pointer_path.is_absolute() else None,
        snapshots_dir / pointer.snapshot_id,
        snapshots_dir / pointer.path,
        snapshots_dir.parent / pointer.path,
        ROOT / pointer.path,
    ]
    for candidate in candidates:
        if candidate is not None and candidate.exists() and candidate.is_dir():
            return candidate
    return None


def _load_investigations_file(path: Path) -> list[Investigation]:
    raw = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(raw, dict):
        return InvestigationList.model_validate(raw).items
    if isinstance(raw, list):
        return [Investigation.model_validate(item) for item in raw]
    raise ValueError(f"Unexpected investigations payload type in {path}")


def _load_chunks_file(path: Path) -> list[TextChunk]:
    if not path.exists():
        return []
    chunks: list[TextChunk] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        chunks.append(TextChunk.model_validate_json(stripped))
    return chunks


def _populate_related_investigations(
    investigations: list[Investigation],
    llm: LLMClient,
) -> list[Investigation]:
    if len(investigations) <= 1:
        return investigations

    needs_related = any(not inv.related_investigations for inv in investigations)
    if not needs_related:
        return investigations

    texts = [
        " ".join(
            part
            for part in (
                inv.title,
                inv.acronym or "",
                inv.objectives or "",
                inv.summary.objective if inv.summary else "",
                " ".join(inv.hardware),
                inv.fuel_phase,
            )
            if part
        )
        for inv in investigations
    ]
    vectors = llm.embed_texts(texts)

    updated: list[Investigation] = []
    for idx, inv in enumerate(investigations):
        if inv.related_investigations:
            updated.append(inv)
            continue
        scored: list[tuple[float, str]] = []
        hw_self = set(inv.hardware)
        for other_idx, other in enumerate(investigations):
            if other.accession == inv.accession:
                continue
            sim = cosine_similarity(vectors[idx], vectors[other_idx])
            hw_bonus = 0.25 if (hw_self and hw_self & set(other.hardware)) else 0.0
            phase_bonus = (
                0.15
                if (inv.fuel_phase != "unknown" and inv.fuel_phase == other.fuel_phase)
                else 0.0
            )
            scored.append((sim + hw_bonus + phase_bonus, other.accession))
        scored.sort(key=lambda pair: (-pair[0], pair[1]))
        related = [acc for _, acc in scored[:3]]
        updated.append(inv.model_copy(update={"related_investigations": related}))
    return updated


@dataclass
class LoadedSnapshot:
    """In-memory snapshot state loaded from latest.json or sample fallback."""

    pointer: SnapshotPointer | None
    snapshot_id: str
    snapshot_date: datetime
    snapshot_dir: Path
    is_sample_fallback: bool
    investigations: list[Investigation]
    investigations_by_id: dict[str, Investigation]
    chunks: list[TextChunk]
    chunk_embeddings: list[list[float]]
    parquet_path: Path | None
    test_count: int
    warnings: list[str] = field(default_factory=list)


class SnapshotLoader:
    """Loads snapshots from Azure Blob Storage or local disk and refreshes every 15 minutes."""

    def __init__(
        self,
        settings: Settings | None = None,
        llm: LLMClient | None = None,
        *,
        clock: Callable[[], float] = time.monotonic,
        blob_fetcher: BlobFetcher | None = None,
    ) -> None:
        self.settings = settings or Settings()
        self.llm = llm or LLMClient(self.settings)
        self._clock = clock
        self._blob_fetcher = blob_fetcher
        self._lock = threading.RLock()
        self._current: LoadedSnapshot | None = None
        self._last_checked_at: float | None = None

    def _default_blob_fetch(self, blob_path: str) -> bytes | None:
        account_url = self.settings.azure_storage_account_url.strip().rstrip("/")
        container = self.settings.azure_storage_container.strip().strip("/")
        if not account_url:
            return None
        url = f"{account_url}/{container}/{blob_path.lstrip('/')}"
        try:
            with httpx.Client(timeout=15.0) as client:
                response = client.get(url)
                if response.status_code == 404:
                    return None
                response.raise_for_status()
                return response.content
        except Exception as exc:
            logger.warning("Azure Blob fetch failed for %s (%s)", blob_path, type(exc).__name__)
            return None

    def _fetch_blob(self, blob_path: str) -> bytes | None:
        if self._blob_fetcher is not None:
            return self._blob_fetcher(blob_path)
        if self.settings.azure_storage_account_url.strip():
            return self._default_blob_fetch(blob_path)
        return None

    def _sync_blob_snapshot(self) -> tuple[SnapshotPointer, Path] | None:
        raw_pointer = self._fetch_blob("latest.json")
        if raw_pointer is None:
            return None
        pointer = SnapshotPointer.model_validate_json(raw_pointer.decode("utf-8"))
        cache_dir = self.settings.snapshots_dir / pointer.snapshot_id
        cache_dir.mkdir(parents=True, exist_ok=True)
        (self.settings.snapshots_dir / "latest.json").write_bytes(raw_pointer)

        container_prefix = self.settings.azure_storage_container.strip().strip("/")
        pointer_rel = pointer.path.strip("/")
        if pointer_rel.startswith(f"{container_prefix}/"):
            pointer_rel = pointer_rel.removeprefix(f"{container_prefix}/")

        for filename in pointer.files:
            target = cache_dir / filename
            if target.exists():
                continue
            data = self._fetch_blob(f"{pointer.snapshot_id}/{filename}")
            if data is None and pointer_rel != pointer.snapshot_id:
                data = self._fetch_blob(f"{pointer_rel}/{filename}")
            if data is not None:
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(data)

        return pointer, cache_dir

    def _read_pointer(self) -> tuple[SnapshotPointer | None, Path | None, list[str]]:
        warnings: list[str] = []
        if self._blob_fetcher is not None or self.settings.azure_storage_account_url.strip():
            try:
                synced = self._sync_blob_snapshot()
                if synced is not None:
                    return synced[0], synced[1], warnings
                warnings.append(
                    "Azure Blob Storage latest.json unavailable; falling back to local snapshot."
                )
            except Exception as exc:
                warnings.append(
                    f"Azure Blob snapshot sync failed ({type(exc).__name__}); using fallback."
                )

        local_pointer = self.settings.snapshots_dir / "latest.json"
        if local_pointer.exists():
            pointer = SnapshotPointer.model_validate_json(local_pointer.read_text(encoding="utf-8"))
            snap_dir = _resolve_snapshot_dir(pointer, self.settings.snapshots_dir)
            if snap_dir is not None:
                return pointer, snap_dir, warnings
            warnings.append(f"Snapshot directory for {pointer.snapshot_id} missing on disk.")

        return None, None, warnings

    def _load_snapshot_from_dir(
        self,
        pointer: SnapshotPointer | None,
        snap_dir: Path | None,
        extra_warnings: list[str],
    ) -> LoadedSnapshot:
        warnings = list(extra_warnings)
        is_sample = pointer is None or snap_dir is None
        target_dir = snap_dir if snap_dir is not None else (ROOT / "snapshots/sample")

        inv_path = target_dir / "investigations.json"
        investigations = _load_investigations_file(inv_path)
        if not is_sample:
            investigations = _populate_related_investigations(investigations, self.llm)
        inv_by_id = {inv.accession: inv for inv in investigations}

        chunks = _load_chunks_file(target_dir / "chunks.jsonl")
        chunk_embeddings = self.llm.embed_texts([chunk.text for chunk in chunks]) if chunks else []

        parquet_candidate = target_dir / "tests.parquet"
        parquet_path = parquet_candidate if parquet_candidate.exists() else None
        if parquet_path is not None:
            with duckdb.connect(":memory:") as conn:
                row = conn.execute(
                    f"SELECT COUNT(*) FROM {_parquet_sql_source(parquet_path)}"
                ).fetchone()
                test_count = int(row[0]) if row else 0
        else:
            test_count = 0

        if pointer is not None:
            snapshot_id = pointer.snapshot_id
            snapshot_date = pointer.created_at
            if pointer.review_status != "reviewed":
                warnings.append(
                    f"Snapshot {snapshot_id} review_status is '{pointer.review_status}'."
                )
        else:
            meta_file = target_dir / "meta.json"
            if meta_file.exists():
                meta_raw = json.loads(meta_file.read_text(encoding="utf-8"))
                snapshot_id = str(meta_raw.get("snapshot_id", "sample-fallback"))
                snapshot_date = datetime.fromisoformat(
                    str(meta_raw["snapshot_date"]).replace("Z", "+00:00")
                )
            else:
                snapshot_id = "sample-fallback"
                snapshot_date = datetime.now(UTC)
            warnings.append("Using baked-in snapshots/sample fallback; no latest.json active.")

        return LoadedSnapshot(
            pointer=pointer,
            snapshot_id=snapshot_id,
            snapshot_date=snapshot_date,
            snapshot_dir=target_dir,
            is_sample_fallback=is_sample,
            investigations=investigations,
            investigations_by_id=inv_by_id,
            chunks=chunks,
            chunk_embeddings=chunk_embeddings,
            parquet_path=parquet_path,
            test_count=test_count,
            warnings=warnings,
        )

    def get_snapshot(self, *, force_refresh: bool = False) -> LoadedSnapshot:
        with self._lock:
            now = self._clock()
            should_check = (
                self._current is None
                or force_refresh
                or self._last_checked_at is None
                or (now - self._last_checked_at) >= self.settings.snapshot_refresh_seconds
            )
            if not should_check and self._current is not None:
                return self._current

            self._last_checked_at = now
            try:
                pointer, snap_dir, extra_warnings = self._read_pointer()
                if (
                    self._current is not None
                    and not force_refresh
                    and pointer is not None
                    and pointer.snapshot_id == self._current.snapshot_id
                ):
                    return self._current
                loaded = self._load_snapshot_from_dir(pointer, snap_dir, extra_warnings)
                self._current = loaded
                return loaded
            except Exception as exc:
                logger.warning("Snapshot reload failed (%s)", type(exc).__name__)
                if self._current is not None:
                    return self._current
                loaded = self._load_snapshot_from_dir(
                    None, None, [f"Snapshot load failed ({type(exc).__name__}); using sample."]
                )
                self._current = loaded
                return loaded

    def query_tests(
        self,
        *,
        accession: str | None = None,
        oxygen_min: float | None = None,
        oxygen_max: float | None = None,
        pressure_min: float | None = None,
        pressure_max: float | None = None,
        limit: int | None = 100,
        offset: int = 0,
    ) -> tuple[list[ExperimentalTest], int]:
        snap = self.get_snapshot()
        if snap.parquet_path is None:
            return [], 0

        clauses: list[str] = []
        params: list[Any] = []
        if accession is not None:
            clauses.append("accession = ?")
            params.append(accession)
        if oxygen_min is not None:
            clauses.append("o2_fraction >= ?")
            params.append(oxygen_min)
        if oxygen_max is not None:
            clauses.append("o2_fraction <= ?")
            params.append(oxygen_max)
        if pressure_min is not None:
            clauses.append("pressure_kpa >= ?")
            params.append(pressure_min)
        if pressure_max is not None:
            clauses.append("pressure_kpa <= ?")
            params.append(pressure_max)

        where_sql = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        source = _parquet_sql_source(snap.parquet_path)

        with duckdb.connect(":memory:") as conn:
            total_row = conn.execute(
                f"SELECT COUNT(*) FROM {source} {where_sql}",
                params,
            ).fetchone()
            total = int(total_row[0]) if total_row else 0
            if total == 0:
                return [], 0

            query_sql = (
                f"SELECT * FROM {source} {where_sql} "
                "ORDER BY accession ASC, source_row ASC, test_id ASC"
            )
            query_params = list(params)
            if limit is not None:
                query_sql += " LIMIT ? OFFSET ?"
                query_params.extend([limit, offset])

            cursor = conn.execute(query_sql, query_params)
            col_names = [desc[0] for desc in cursor.description]
            rows = [
                row_from_duckdb_record(
                    dict(zip(col_names, record, strict=True)),
                    default_retrieved_at=snap.snapshot_date,
                )
                for record in cursor.fetchall()
            ]
        return rows, total

    def query_tests_by_sql_filter(self, sql_filter: SqlRowFilter) -> list[ExperimentalTest]:
        snap = self.get_snapshot()
        if snap.parquet_path is None:
            return []

        clauses: list[str] = ["COALESCE(evidence_type, '') != 'mock'"]
        params: list[Any] = []

        if sql_filter.accessions:
            placeholders = ", ".join("?" for _ in sql_filter.accessions)
            clauses.append(f"accession IN ({placeholders})")
            params.extend(sql_filter.accessions)
        if sql_filter.fuel:
            clauses.append("LOWER(COALESCE(fuel, '')) LIKE ?")
            params.append(f"%{sql_filter.fuel.casefold()}%")
        if sql_filter.fuel_phase:
            clauses.append("fuel_phase = ?")
            params.append(sql_filter.fuel_phase)
        if sql_filter.o2_min is not None:
            clauses.append("o2_fraction >= ?")
            params.append(sql_filter.o2_min)
        if sql_filter.o2_max is not None:
            clauses.append("o2_fraction <= ?")
            params.append(sql_filter.o2_max)
        if sql_filter.pressure_min is not None:
            clauses.append("pressure_kpa >= ?")
            params.append(sql_filter.pressure_min)
        if sql_filter.pressure_max is not None:
            clauses.append("pressure_kpa <= ?")
            params.append(sql_filter.pressure_max)
        if sql_filter.flow_min is not None:
            clauses.append("flow_cm_s >= ?")
            params.append(sql_filter.flow_min)
        if sql_filter.flow_max is not None:
            clauses.append("flow_cm_s <= ?")
            params.append(sql_filter.flow_max)
        if sql_filter.diluent:
            clauses.append("LOWER(COALESCE(diluent, '')) LIKE ?")
            params.append(f"%{sql_filter.diluent.casefold()}%")
        if sql_filter.outcome:
            clauses.append("outcome = ?")
            params.append(sql_filter.outcome)

        where_sql = f"WHERE {' AND '.join(clauses)}"
        source = _parquet_sql_source(snap.parquet_path)
        sql = (
            f"SELECT * FROM {source} {where_sql} "
            "ORDER BY CASE WHEN review_status = 'reviewed' THEN 0 ELSE 1 END, "
            "accession ASC, source_row ASC, test_id ASC "
            "LIMIT ?"
        )
        params.append(sql_filter.limit)

        with duckdb.connect(":memory:") as conn:
            cursor = conn.execute(sql, params)
            col_names = [desc[0] for desc in cursor.description]
            return [
                row_from_duckdb_record(
                    dict(zip(col_names, record, strict=True)),
                    default_retrieved_at=snap.snapshot_date,
                )
                for record in cursor.fetchall()
            ]
