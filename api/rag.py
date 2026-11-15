"""Grounded RAG retrieval, structured SQL filtering, rate limiting, and SSE chat."""

from __future__ import annotations

import json
import logging
import math
import re
import threading
import time
from collections import Counter, defaultdict, deque
from collections.abc import Callable, Iterator

from fastapi import HTTPException

from api.answers import document_answer, structured_answer
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

    if re.search(r"\bsummari[sz](?:e|ation)|\bsummary\b|\boverview\b", question, re.I):
        ids = set(investigation_ids or re.findall(r"\bPSI-\d+\b", question.upper()))
        if not ids:
            ids = {
                inv.accession
                for inv in snap.investigations
                if inv.acronym
                and re.search(r"(?<!\w)" + re.escape(inv.acronym) + r"(?!\w)", question, re.I)
            }
        priorities = {"objectives": 0, "approach": 1, "description": 2, "research_impacts": 3}
        fields = [
            c
            for c in snap.chunks
            if c.accession in ids
            and c.source_kind == "investigation_field"
            and c.field_name in priorities
        ]
        first_fields = {}
        for chunk in sorted(fields, key=lambda c: c.chunk_id):
            first_fields.setdefault((chunk.accession, chunk.field_name), chunk)
        return sorted(first_fields.values(), key=lambda c: (priorities[c.field_name], c.chunk_id))[
            :top_k
        ]

    q_vec = llm.embed_text(question)
    generic = {"experiment", "experiments", "report", "reports", "reported", "study", "studies"}

    def tokens(text: str) -> list[str]:
        values = re.findall(r"[a-z0-9]+", text.casefold())
        return [
            "decrease"
            if re.fullmatch(r"reduc\w*|decreas\w*|slower|lower", t)
            else "spread"
            if t == "spreading"
            else t
            for t in values
            if len(t) >= 2 and t not in _STOPWORDS and t not in generic
        ]

    query = set(tokens(question))
    allowed_ids = set(investigation_ids or re.findall(r"\bPSI-\d+\b", question.upper()))
    candidates = []
    for idx, chunk in enumerate(snap.chunks):
        inv = snap.investigations_by_id.get(chunk.accession or "")
        if inv is None or inv.fixture or (allowed_ids and chunk.accession not in allowed_ids):
            continue
        if chunk.source_kind == "summary" and inv.summary is None:
            continue
        candidates.append((idx, chunk, tokens(chunk.text)))
    frequencies = Counter(t for _, _, words in candidates for t in set(words))
    avg_length = sum(len(words) for _, _, words in candidates) / max(1, len(candidates))
    scored = []
    comparative_spread = {"decrease", "spread"} <= query
    for idx, chunk, words in candidates:
        counts = Counter(words)
        overlap = query & counts.keys()
        accession_match = chunk.accession in question.upper()
        if not overlap and not accession_match:
            continue
        bm25 = 0.0
        for term in overlap:
            idf = math.log(
                1 + (len(candidates) - frequencies[term] + 0.5) / (frequencies[term] + 0.5)
            )
            tf = counts[term]
            bm25 += idf * tf * 2.2 / (tf + 1.2 * (0.25 + 0.75 * len(words) / max(1, avg_length)))
        vec = snap.chunk_embeddings[idx] if idx < len(snap.chunk_embeddings) else []
        score = bm25 + 0.5 * max(0, cosine_similarity(q_vec, vec))
        if accession_match:
            score += 2
        if comparative_spread:
            # Require the actual spread concept. Generic flame operations are not findings.
            if "spread" not in counts:
                continue
            sentences = re.split(r"(?<=[.!?])\s+|\n", chunk.text)
            if any({"decrease", "spread"} <= set(tokens(sentence)) for sentence in sentences):
                score += 12
        scored.append((score, -idx, chunk))
    scored.sort(key=lambda item: (item[0], item[1]), reverse=True)
    selected = []
    per_study: Counter[str] = Counter()
    for _, _, chunk in scored:
        if not allowed_ids and per_study[chunk.accession] >= 2:
            continue
        selected.append(chunk)
        per_study[chunk.accession] += 1
        if len(selected) >= top_k:
            break
    return selected


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


def _source_answer(
    question: str, chunks: list[TextChunk], snap: LoadedSnapshot
) -> AnswerEvent | None:
    summary = bool(re.search(r"\bsummari[sz](?:e|ation)|\bsummary\b|\boverview\b", question, re.I))
    comparison = bool(
        re.search(r"spread", question, re.I)
        and re.search(r"reduc|decreas|slower|lower", question, re.I)
    )
    if not summary and not comparison:
        return None
    selected = []
    excerpts = []
    seen = set()
    for chunk in chunks:
        inv = snap.investigations_by_id.get(chunk.accession)
        if inv is None:
            continue
        if summary:
            if chunk.source_kind != "investigation_field":
                continue
            label = (chunk.field_name or "source").replace("_", " ").capitalize()
            # Show the original metadata's first complete sentence, without
            # changing its meaning or presenting objectives as observed results.
            text = chunk.text.strip()
            end = re.search(r"(?<![0-9])[.!?](?:\s|$)", text)
            if end:
                text = text[: end.start() + 1]
            excerpt = f"{label}: {text}"
        else:
            if chunk.source_kind != "document":
                continue
            sentences = re.split(r"(?<=[.!?])\s+", " ".join(chunk.text.split()))
            matching = [
                sentence
                for sentence in sentences
                if re.search(
                    r"\bspread(?:ing)?(?:\s+rate)?\b.{0,200}\b(?:decreases?|decreased|reduced|slower|lower)\b",
                    sentence,
                    re.I,
                )
                and not re.search(r"\b(?:aim|objective|plan|will|hypothes)\w*\b", sentence, re.I)
            ]
            if not matching:
                continue
            excerpt = matching[0]
        key = (chunk.accession, excerpt)
        if key in seen:
            continue
        seen.add(key)
        selected.append(chunk)
        excerpts.append((inv, excerpt))
    if not selected:
        return None
    citations = build_citations(snap, selected, [])
    lines = [
        "Source-based investigation summary:"
        if summary
        else "Reported flame-spread comparisons (conditions apply):"
    ]
    for (inv, excerpt), citation in zip(excerpts, citations, strict=True):
        lines.append(
            f"- {inv.acronym or inv.accession} ({inv.accession}): {excerpt} "
            f"{format_citation_tag(citation, inv.doi)}"
        )
    if summary:
        lines.append(
            "Objectives describe the research purpose; "
            "they are not proof of an experimental outcome."
        )
    else:
        lines.append(
            "These are retrieved comparisons under the reported conditions, "
            "not a universal reduction or a safety certification."
        )
    return AnswerEvent(text="\n".join(lines), status="supported", citations=citations)


def stream_chat_events(
    request: ChatRequest,
    *,
    loader: SnapshotLoader,
    llm: LLMClient,
    mock_mode: bool,
    cancelled: Callable[[], bool] = lambda: False,
) -> Iterator[str]:
    if cancelled():
        return
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
        if cancelled():
            return
        structured = structured_answer(request, snap, loader, build_citations)
        if cancelled():
            return
        if structured is not None:
            yield sse_frame(
                "progress",
                ProgressEvent(
                    stage="retrieval",
                    message="Checked structured source records and requested fields.",
                ).model_dump(),
            )
            yield sse_frame(
                "progress",
                ProgressEvent(
                    stage="answer", message="Prepared a source-grounded response."
                ).model_dump(),
            )
            yield sse_frame("answer", structured.model_dump(mode="json"))
            yield sse_frame(
                "done",
                DoneEvent(
                    finish_reason="stop"
                    if structured.status == "supported"
                    else "insufficient_evidence"
                ).model_dump(),
            )
            return
        top_chunks = retrieve_top_chunks(
            request.question,
            snap,
            llm,
            investigation_ids=request.investigation_ids,
            top_k=8,
        )
        if cancelled():
            return
        # Structured metadata summaries and literal comparative findings do not
        # require a model to approve facts already present in the source records.
        direct = _source_answer(request.question, top_chunks, snap) or document_answer(
            request.question, top_chunks, snap, build_citations
        )
        if direct is not None:
            yield sse_frame(
                "progress",
                ProgressEvent(
                    stage="retrieval", message="Found source-backed evidence."
                ).model_dump(),
            )
            yield sse_frame("answer", direct.model_dump(mode="json"))
            yield sse_frame("done", DoneEvent(finish_reason="stop").model_dump())
            return
        matched_rows = retrieve_matching_rows(
            request.question,
            snap,
            loader,
            llm,
            investigation_ids=request.investigation_ids,
            top_chunks=top_chunks,
        )
        if cancelled():
            return
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
        if cancelled():
            return
        answer_text = llm.generate_grounded_answer(
            request.question,
            top_chunks,
            matched_rows,
            citations,
            doi_by_accession=doi_by_accession,
        )
        if cancelled():
            return
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
