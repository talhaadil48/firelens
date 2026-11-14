"""Data sources behind the API (build-steps 6.2).

MockStore      Phase 2 fixtures (snapshots/sample); no test rows.
SnapshotStore  one snapshot folder: DuckDB over tests.parquet, records in memory.
StoreManager   follows snapshots/latest.json; re-checks it every 15 minutes and swaps the
               new snapshot in from a background thread, so requests never wait on a load.
Blob Storage loading plugs in later by syncing the container into ``snapshot_dir``.
"""

import json
import logging
import math
import threading
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

import duckdb

from api.models import (
    DataMode,
    ExperimentalTest,
    Investigation,
    InvestigationList,
    MetaResponse,
)

log = logging.getLogger("firelens.store")
PROVENANCE = [
    "source_url",
    "source_file",
    "source_version",
    "retrieved_at",
    "source_row",
    "source_sha256",
    "is_mock",
]


@dataclass
class TestFilter:
    accession: str | None = None
    o2_min: float | None = None
    o2_max: float | None = None
    pressure_min: float | None = None
    pressure_max: float | None = None
    flow_min: float | None = None
    flow_max: float | None = None
    fuel_phase: str | None = None
    outcome: str | None = None
    reviewed_only: bool = False

    def sql(self) -> tuple[str, list]:
        clauses, params = [], []
        for column, op, value in [
            ("accession", "=", self.accession),
            ("o2_fraction", ">=", self.o2_min),
            ("o2_fraction", "<=", self.o2_max),
            ("pressure_kpa", ">=", self.pressure_min),
            ("pressure_kpa", "<=", self.pressure_max),
            ("flow_cm_s", ">=", self.flow_min),
            ("flow_cm_s", "<=", self.flow_max),
            ("fuel_phase", "=", self.fuel_phase),
            ("outcome", "=", self.outcome),
        ]:
            if value is not None:
                clauses.append(f"{column} {op} ?")
                params.append(value)
        if self.reviewed_only:
            clauses.append("review_status = 'reviewed'")
        return (" WHERE " + " AND ".join(clauses)) if clauses else "", params


class BaseStore:
    mode: DataMode
    snapshot_id: str
    investigations: list[Investigation]
    tests: list[ExperimentalTest]

    def __init__(self) -> None:
        self.by_id = {}

    def _index(self) -> None:
        self.by_id = {item.accession: item for item in self.investigations}

    def query_tests(self, flt: TestFilter) -> list[ExperimentalTest]:
        return []

    def meta(self) -> MetaResponse:
        raise NotImplementedError


class MockStore(BaseStore):
    mode: DataMode = "mock"

    def __init__(self, sample_dir: Path):
        super().__init__()
        self.sample_dir = sample_dir
        listing = InvestigationList.model_validate_json(
            (sample_dir / "investigations.json").read_text(encoding="utf-8")
        )
        self.investigations = listing.items
        self.tests = []
        self._meta = MetaResponse.model_validate_json(
            (sample_dir / "meta.json").read_text(encoding="utf-8")
        )
        self.snapshot_id = self._meta.snapshot_id
        self._index()

    def meta(self) -> MetaResponse:
        return self._meta.model_copy(deep=True)


def _clean(value):
    if isinstance(value, float) and math.isnan(value):
        return None
    return value


class SnapshotStore(BaseStore):
    mode: DataMode = "snapshot"

    def __init__(self, folder: Path):
        super().__init__()
        self.folder = folder
        self.info = json.loads((folder / "snapshot.json").read_text(encoding="utf-8"))
        self.snapshot_id = self.info["snapshot_id"]
        listing = InvestigationList.model_validate_json(
            (folder / "investigations.json").read_text(encoding="utf-8")
        )
        self.investigations = listing.items
        self._index()
        self.db = duckdb.connect(":memory:")
        self.db.execute(
            "CREATE TABLE tests AS SELECT row_number() OVER () - 1 AS idx, * FROM read_parquet(?)",
            [str(folder / "tests.parquet")],
        )
        self._lock = threading.Lock()  # one DuckDB connection; serialize queries
        cursor = self.db.execute("SELECT * EXCLUDE (idx) FROM tests ORDER BY idx")
        columns = [c[0] for c in cursor.description]
        self.tests = [
            self._row_to_test(dict(zip(columns, r, strict=True))) for r in cursor.fetchall()
        ]
        self.chunk_count = self.info.get("chunk_count", 0)

    @staticmethod
    def _row_to_test(row: dict) -> ExperimentalTest:
        row = {k: _clean(v) for k, v in row.items()}
        provenance = {k: row.pop(k) for k in PROVENANCE}
        provenance["retrieved_at"] = provenance["retrieved_at"]
        row["metrics"] = json.loads(row["metrics"] or "{}")
        row["notes"] = json.loads(row["notes"] or "[]")
        return ExperimentalTest.model_validate({**row, "provenance": provenance})

    def query_tests(self, flt: TestFilter) -> list[ExperimentalTest]:
        where, params = flt.sql()
        with self._lock:
            indexes = self.db.execute(f"SELECT idx FROM tests{where} ORDER BY idx", params)
            return [self.tests[i] for (i,) in indexes.fetchall()]

    def sql(self, query: str, params: list | None = None) -> list[tuple]:
        """Read-only SQL for later stages (chat row filters build parameterized queries)."""
        with self._lock:
            return self.db.execute(query, params or []).fetchall()

    def meta(self) -> MetaResponse:
        return MetaResponse(
            mode="snapshot",
            snapshot_id=self.snapshot_id,
            snapshot_date=datetime.fromisoformat(self.info["created_at"]),
            psi_retrieved_at=datetime.fromisoformat(self.info["psi_retrieved_at"]),
            investigation_count=len(self.investigations),
            test_count=len(self.tests),
            reviewed_test_count=self.info.get("reviewed_test_count", 0),
            warnings=[],
        )


def read_pointer(snapshot_dir: Path) -> str:
    pointer = json.loads((snapshot_dir / "latest.json").read_text(encoding="utf-8"))
    path = pointer["path"].strip("/")
    if "/" in path or path.startswith(".") or not path:
        raise ValueError("latest.json must point to a folder directly under the snapshot dir")
    return path


class StoreManager:
    def __init__(self, mode: str, snapshot_dir: Path, pointer_check_seconds: int):
        self.snapshot_dir = snapshot_dir
        self.interval = pointer_check_seconds
        self.mode = mode
        self._loading = False
        self._checked = time.monotonic()
        if mode == "mock":
            self._store: BaseStore = MockStore(snapshot_dir / "sample")
        else:
            self._store = SnapshotStore(snapshot_dir / read_pointer(snapshot_dir))
        log.info("Loaded %s data: %s", mode, self._store.snapshot_id)

    @property
    def store(self) -> BaseStore:
        if self.mode == "snapshot" and time.monotonic() - self._checked > self.interval:
            self._checked = time.monotonic()
            self._check_pointer()
        return self._store

    def set_store(self, store: BaseStore) -> None:
        self._store = store

    def _check_pointer(self) -> None:
        try:
            target = read_pointer(self.snapshot_dir)
        except (OSError, ValueError, KeyError) as exc:
            log.warning(
                "Snapshot pointer unreadable (%s); keeping %s", exc, self._store.snapshot_id
            )
            return
        if target == self._store.snapshot_id or self._loading:
            return
        self._loading = True

        def load() -> None:
            try:
                fresh = SnapshotStore(self.snapshot_dir / target)
                self._store = fresh  # atomic reference swap
                log.info("Swapped to snapshot %s", target)
            except Exception:  # keep serving the last good snapshot
                log.exception("Failed to load snapshot %s; keeping the current one", target)
            finally:
                self._loading = False

        threading.Thread(target=load, daemon=True).start()


def now() -> datetime:
    return datetime.now(UTC)
