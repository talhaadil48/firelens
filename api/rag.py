"""Grounded RAG retrieval, structured SQL filtering, rate limiting, and SSE chat."""

from __future__ import annotations

import json
import logging
import re
import threading
import time
from collections import defaultdict, deque
from collections.abc import Callable, Iterator

from fastapi import HTTPException

from api.llm import LLMClient, SqlRowFilter, cosine_similarity, format_citation_tag
from api.models import (
    AnswerEvent,
    ChatRequest,
    Citation,
    DoneEvent,
    EvidenceType,
    ExperimentalTest,
    ProgressEvent,
    Provenance,
    TextChunk,
)
from api.snapshot import LoadedSnapshot, SnapshotLoader

logger = logging.getLogger(__name__)

_STOPWORDS = frozenset(
    {
        "a",
        "about",
        "an",
        "and",
        "are",
        "as",
        "at",
        "be",
        "been",
        "between",
        "by",
        "can",
        "did",
        "do",
        "does",
        "for",
        "from",
        "had",
        "has",
        "have",
        "how",
        "in",
        "into",
        "is",
        "it",
        "of",
        "on",
        "or",
        "that",
        "the",
        "these",
        "this",
        "those",
        "to",
        "was",
        "were",
        "what",
        "when",
        "where",
        "which",
        "who",
        "why",
        "will",
        "with",
    }
)

_OUT_OF_SCOPE_PATTERN = re.compile(
    r"\b(?:"
    r"rockets?|propellants?|thrusters?|hypergolics?|hydrazine|"
    r"solid\s+rocket|rocket\s+engines?|rocket\s+motors?|lox|kerolox|methalox|"
    r"launch\s+vehicles?"
    r")\b",
    re.IGNORECASE,
)

_TEST_QUERY_KEYWORDS = frozenset(
    {
        "test",
        "tests",
        "row",
        "rows",
        "o2",
        "oxygen",
        "pressure",
        "kpa",
        "flow",
        "airflow",
        "velocity",
        "fuel",
        "diluent",
        "helium",
        "nitrogen",
        "co2",
        "ignited",
        "extinguished",
        "outcome",
        "burned",
    }
)


class RateLimiter:
    """Sliding-window per-IP rate limiter for /chat."""

    def __init__(
        self,
        limit_per_minute: int = 20,
        *,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.limit_per_minute = max(1, limit_per_minute)
        self._clock = clock
        self._lock = threading.Lock()
        self._buckets: dict[str, deque[float]] = defaultdict(deque)

    def check(self, client_ip: str) -> None:
        now = self._clock()
        cutoff = now - 60.0
        with self._lock:
            bucket = self._buckets[client_ip]
            while bucket and bucket[0] <= cutoff:
                bucket.popleft()
            if len(bucket) >= self.limit_per_minute:
                raise HTTPException(
                    status_code=429,
                    detail="Rate limit exceeded for /chat. Please retry in a minute.",
                )
            bucket.append(now)

    def reset(self) -> None:
        with self._lock:
            self._buckets.clear()


def sse_frame(event: str, payload: dict) -> str:
    return f"event: {event}\ndata: {json.dumps(payload, ensure_ascii=False)}\n\n"


def is_out_of_scope(question: str) -> str | None:
    if _OUT_OF_SCOPE_PATTERN.search(question):
        return (
            "Insufficient evidence (out of scope): FireLens covers NASA PSI microgravity and "
            "spacecraft cabin combustion investigations only; rockets and propellants are out of "
            "scope."
        )
    return None


def _content_tokens(text: str) -> set[str]:
    tokens = re.findall(r"[a-z0-9]+", text.casefold())
    return {t for t in tokens if len(t) >= 2 and t not in _STOPWORDS}


def retrieve_top_chunks(
    question: str,
    snap: LoadedSnapshot,
    llm: LLMClient,
    *,
    investigation_ids: list[str] | None = None,
    top_k: int = 8,
) -> list[TextChunk]:
    if not snap.chunks:
        return []

    q_vec = llm.embed_text(question)
    q_tokens = _content_tokens(question)
    allowed_ids = set(investigation_ids or [])
    q_upper = question.upper()

    scored: list[tuple[float, int, TextChunk]] = []
    for idx, chunk in enumerate(snap.chunks):
        inv = snap.investigations_by_id.get(chunk.accession or "")
        if inv is None or inv.fixture:
            continue
        if chunk.source_kind == "summary" and inv.summary is None:
            continue
        if allowed_ids and chunk.accession not in allowed_ids:
            continue
        vec = snap.chunk_embeddings[idx] if idx < len(snap.chunk_embeddings) else []
        sim = cosine_similarity(q_vec, vec)
        chunk_tokens = _content_tokens(f"{chunk.accession or ''} {chunk.source_file} {chunk.text}")
        overlap_hits = len(q_tokens & chunk_tokens) if q_tokens else 0
        overlap_ratio = overlap_hits / max(1, len(q_tokens))
        accession_boost = 0.25 if (chunk.accession and chunk.accession in q_upper) else 0.0

        min_sim = 0.30 if llm.is_live else 0.25
        if overlap_hits == 0 and sim < min_sim and accession_boost == 0.0:
            continue

        score = 0.55 * max(0.0, sim) + 0.45 * overlap_ratio + accession_boost
        scored.append((score, -idx, chunk))

    scored.sort(key=lambda item: (item[0], item[1]), reverse=True)
    return [chunk for _, _, chunk in scored[:top_k]]


def _has_active_filter(sql_filter: SqlRowFilter) -> bool:
    return any(
        [
            bool(sql_filter.accessions),
            sql_filter.fuel is not None,
            sql_filter.fuel_phase is not None,
            sql_filter.o2_min is not None,
            sql_filter.o2_max is not None,
            sql_filter.pressure_min is not None,
            sql_filter.pressure_max is not None,
            sql_filter.flow_min is not None,
            sql_filter.flow_max is not None,
            sql_filter.diluent is not None,
            sql_filter.outcome is not None,
        ]
    )


def retrieve_matching_rows(
    question: str,
    snap: LoadedSnapshot,
    loader: SnapshotLoader,
    llm: LLMClient,
    *,
    investigation_ids: list[str] | None = None,
    top_chunks: list[TextChunk] | None = None,
) -> list[ExperimentalTest]:
    if snap.parquet_path is None:
        return []

    sql_filter = llm.propose_sql_filter(question, investigation_ids)
    q_tokens = _content_tokens(question)

    if not _has_active_filter(sql_filter):
        if not top_chunks or not (q_tokens & _TEST_QUERY_KEYWORDS):
            return []
        chunk_accessions = list(
            dict.fromkeys(chunk.accession for chunk in top_chunks if chunk.accession is not None)
        )
        if not chunk_accessions:
            return []
        sql_filter = sql_filter.model_copy(update={"accessions": chunk_accessions})

    return [
        row
        for row in loader.query_tests_by_sql_filter(sql_filter)
        if row.record_kind == "individual_test"
        and row.evidence_type == EvidenceType.MEASUREMENT
        and not row.provenance.is_mock
    ]


def build_citations(
    snap: LoadedSnapshot,
    chunks: list[TextChunk],
    rows: list[ExperimentalTest],
) -> list[Citation]:
    citations: list[Citation] = []
    seen_ids: set[str] = set()

    for chunk in chunks:
        if chunk.accession is None:
            continue
        cid = f"chunk:{chunk.chunk_id}"
        if cid in seen_ids:
            continue
        seen_ids.add(cid)
        inv = snap.investigations_by_id.get(chunk.accession)
        locator = (
            f"{chunk.source_file} p.{chunk.page}"
            if chunk.page is not None
            else (chunk.field_name or chunk.source_file)
        )
        provenance = Provenance(
            source_url=chunk.source_url,
            source_file=chunk.source_file,
            source_version=chunk.source_version or (inv.version if inv else "1"),
            retrieved_at=inv.retrieved_at if inv else snap.snapshot_date,
            page=chunk.page,
            source_sha256=chunk.sha256,
            is_mock=False,
        )
        citations.append(
            Citation(
                id=cid,
                accession=chunk.accession,
                locator=locator,
                supporting_text=chunk.text,
                provenance=provenance,
            )
        )

    for row in rows[:8]:
        cid = f"row:{row.accession}:{row.test_id}"
        if cid in seen_ids:
            continue
        seen_ids.add(cid)
        src_file = row.source_file or row.provenance.source_file
        details = [f"test_id={row.test_id}"]
        if row.fuel:
            details.append(f"fuel={row.fuel}")
        if row.o2_fraction is not None:
            details.append(f"o2_fraction={row.o2_fraction}")
        if row.pressure_kpa is not None:
            details.append(f"pressure_kpa={row.pressure_kpa}")
        if row.flow_cm_s is not None:
            details.append(f"flow_cm_s={row.flow_cm_s}")
        if row.outcome:
            details.append(f"outcome={row.outcome}")
        citations.append(
            Citation(
                id=cid,
                accession=row.accession,
                locator=f"{src_file} row {row.source_row}",
                supporting_text=", ".join(details),
                provenance=row.provenance,
            )
        )

    return citations


def stream_chat_events(
    request: ChatRequest,
    *,
    loader: SnapshotLoader,
    llm: LLMClient,
    mock_mode: bool,
) -> Iterator[str]:
    if mock_mode:
        yield sse_frame(
            "progress",
            ProgressEvent(
                stage="retrieval", message="Offline contract mock; no LLM called."
            ).model_dump(),
        )
        yield sse_frame(
            "answer",
            AnswerEvent(
                text=(
                    "Insufficient evidence: Phase 2 contains catalogue metadata, "
                    "not experimental findings."
                ),
                status="insufficient_evidence",
                citations=[],
            ).model_dump(mode="json"),
        )
        yield sse_frame("done", DoneEvent(finish_reason="insufficient_evidence").model_dump())
        return

    try:
        refusal = is_out_of_scope(request.question)
        if refusal is not None:
            yield sse_frame(
                "progress",
                ProgressEvent(
                    stage="retrieval",
                    message="Checked scope guard; query is outside NASA PSI combustion scope.",
                ).model_dump(),
            )
            yield sse_frame(
                "answer",
                AnswerEvent(
                    text=refusal,
                    status="insufficient_evidence",
                    citations=[],
                ).model_dump(mode="json"),
            )
            yield sse_frame("done", DoneEvent(finish_reason="insufficient_evidence").model_dump())
            return

        snap = loader.get_snapshot()
        top_chunks = retrieve_top_chunks(
            request.question,
            snap,
            llm,
            investigation_ids=request.investigation_ids,
            top_k=8,
        )
        matched_rows = retrieve_matching_rows(
            request.question,
            snap,
            loader,
            llm,
            investigation_ids=request.investigation_ids,
            top_chunks=top_chunks,
        )
        citations = build_citations(snap, top_chunks, matched_rows)

        if not citations:
            yield sse_frame(
                "progress",
                ProgressEvent(
                    stage="retrieval",
                    message="Searched snapshot chunks and test rows; no matching PSI evidence.",
                ).model_dump(),
            )
            yield sse_frame(
                "answer",
                AnswerEvent(
                    text=(
                        "Insufficient evidence: no matching NASA PSI chunks or test rows were "
                        "retrieved for this question."
                    ),
                    status="insufficient_evidence",
                    citations=[],
                ).model_dump(mode="json"),
            )
            yield sse_frame("done", DoneEvent(finish_reason="insufficient_evidence").model_dump())
            return

        yield sse_frame(
            "progress",
            ProgressEvent(
                stage="retrieval",
                message=(
                    f"Retrieved {len(top_chunks)} text chunks and "
                    f"{len(matched_rows)} SQL test rows."
                ),
            ).model_dump(),
        )
        yield sse_frame(
            "progress",
            ProgressEvent(
                stage="answer",
                message="Generating citation-grounded response.",
            ).model_dump(),
        )

        doi_by_accession = {acc: inv.doi for acc, inv in snap.investigations_by_id.items()}
        answer_text = llm.generate_grounded_answer(
            request.question,
            top_chunks,
            matched_rows,
            citations,
            doi_by_accession=doi_by_accession,
        )
        insufficient = not answer_text.strip() or answer_text.lstrip().lower().startswith(
            "insufficient evidence"
        )
        used_citations = [
            c
            for c in citations
            if format_citation_tag(c, doi_by_accession.get(c.accession)) in answer_text
        ]
        insufficient = insufficient or not used_citations
        yield sse_frame(
            "answer",
            AnswerEvent(
                text=answer_text if answer_text.strip() else "Insufficient evidence.",
                status="insufficient_evidence" if insufficient else "supported",
                citations=[] if insufficient else used_citations,
            ).model_dump(mode="json"),
        )
        yield sse_frame(
            "done",
            DoneEvent(
                finish_reason="insufficient_evidence" if insufficient else "stop"
            ).model_dump(),
        )
    except Exception as exc:
        logger.exception("Error while streaming /chat response (%s)", type(exc).__name__)
        yield sse_frame("done", DoneEvent(finish_reason="error").model_dump())
