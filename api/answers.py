"""Source-backed answers for structured measurement requests and study identity."""

from __future__ import annotations

import hashlib
import re
import unicodedata
from collections.abc import Callable

from api.llm import (
    _ACRONYM_TO_ACCESSION,
    SqlRowFilter,
    deterministic_sql_filter,
    format_citation_tag,
)
from api.models import AnswerEvent, ChatRequest, Citation, Provenance
from api.snapshot import LoadedSnapshot, SnapshotLoader


def snapshot_citation(snap, inv, text):
    path = snap.snapshot_dir / "investigations.json"
    return Citation(
        id=f"availability:{inv.accession}",
        accession=inv.accession,
        locator=f"snapshot {snap.snapshot_id}: investigation metadata and availability",
        supporting_text=text,
        provenance=Provenance(
            source_url=inv.source_url,
            source_file="investigations.json",
            source_version=snap.snapshot_id,
            retrieved_at=snap.snapshot_date,
            source_sha256=hashlib.sha256(path.read_bytes()).hexdigest() if path.exists() else None,
        ),
    )


def _answer(text, citations, supported=False):
    return AnswerEvent(
        text=text, citations=citations, status="supported" if supported else "insufficient_evidence"
    )


def structured_answer(
    request: ChatRequest, snap: LoadedSnapshot, loader: SnapshotLoader, cite: Callable
) -> AnswerEvent | None:
    question = request.question
    # A named study followed by a contradictory PSI identifier needs correction,
    # not silent replacement of the user's selected scope.
    for pattern, accession in _ACRONYM_TO_ACCESSION:
        for match in pattern.finditer(question):
            adjacent = re.match(r"\s*\(\s*(PSI-\d+)\s*\)", question[match.end() :], re.I)
            if (
                adjacent
                and adjacent[1].upper() != accession
                and accession in snap.investigations_by_id
            ):
                wrong = snap.investigations_by_id.get(adjacent[1].upper())
                right = snap.investigations_by_id[accession]
                text = (
                    f"Study identity correction: {match[0]} is {accession}, "
                    f"not {adjacent[1].upper()}. "
                )
                if wrong:
                    text += f"{wrong.accession} is {wrong.acronym or wrong.title}. "
                text += (
                    f"Choose {accession} to ask about {match[0]}. "
                    "The selected investigation has not been changed."
                )
                citations = [
                    snapshot_citation(snap, inv, inv.title) for inv in [right, wrong] if inv
                ]
                return _answer(
                    text
                    + " "
                    + " ".join(
                        format_citation_tag(c, snap.investigations_by_id[c.accession].doi)
                        for c in citations
                    ),
                    citations,
                    True,
                )
    q = question.casefold()
    numerical = bool(re.search(r"oxygen|\bo2\b|pressure|airflow|air\s*flow|velocit|flow_cm_s", q))
    records = bool(re.search(r"test|run|measur|compar|which|what|list", q))
    explanatory = bool(re.match(r"\s*(why|how)\b", q))
    if (
        not numerical
        or not records
        or explanatory
        or re.search(r"objective|hypothes|phenomena|behavior|findings", q)
    ):
        return None
    plan = deterministic_sql_filter(question, request.investigation_ids)
    scoped = loader.query_tests_by_sql_filter(
        SqlRowFilter(accessions=plan.accessions), all_matches=True
    )
    scope_ids = plan.accessions or sorted({row.accession for row in scoped})
    if re.search(r"thermal\s+runaway|lithium[ -]ion|martian\s+dust", q):
        # Table rows must identify the requested subject. An unrelated combustion
        # row with similar numbers cannot establish a battery experiment.
        subject_rows = [
            r
            for r in scoped
            if re.search(r"lithium|battery|batteries|thermal runaway", r.fuel or "", re.I)
        ]
        if not subject_rows:
            return _answer(
                (
                    "No matching test for the requested battery or dust-storm scenario "
                    "is represented in the imported rows. This snapshot cannot verify "
                    "the proposed subject and conditions. This does not establish that "
                    "NASA has never studied the subject."
                ),
                [],
            )
    rows = loader.query_tests_by_sql_filter(plan, all_matches=True)
    requested = []
    if re.search(r"oxygen|\bo2\b", q):
        requested.append(("o2_fraction", "oxygen fraction"))
    if re.search(r"pressure", q):
        requested.append(("pressure_kpa", "pressure (kPa)"))
    if re.search(r"airflow|air\s*flow|velocit|flow_cm_s", q):
        requested.append(("flow_cm_s", "airflow velocity (cm/s)"))
    notes = []
    availability = []
    for accession in scope_ids:
        inv = snap.investigations_by_id.get(accession)
        if not inv:
            continue
        own = [r for r in scoped if r.accession == accession]
        missing = [
            label
            for field, label in requested
            if not any(getattr(r, field) is not None for r in own)
        ]
        text = f"{accession} is {inv.acronym or inv.title}."
        if missing:
            text += (
                " No exact numeric "
                + ", ".join(missing)
                + " values are available in its imported test rows."
            )
            notes.append(text)
            setting_names = {
                cell.column.strip()
                for r in own
                for cell in r.source_cells
                if re.search(r"restrictor|fan display|air display", cell.column, re.I)
            }
            if setting_names and any(field == "flow_cm_s" for field, _ in requested):
                notes.append(
                    "Source fields "
                    + ", ".join(sorted(setting_names))
                    + " are equipment settings; no calibration to cm/s is supplied here."
                )
        if not rows or missing:
            availability.append(snapshot_citation(snap, inv, text))
    available = [r for r in rows if any(getattr(r, field) is not None for field, _ in requested)]
    if not rows:
        fuel_labels = sorted({r.fuel for r in scoped if r.fuel})
        detail = (
            " Available fuel labels include " + ", ".join(fuel_labels[:8]) + "."
            if fuel_labels
            else ""
        )
        text = (
            "No individual test rows match the requested study, fuel and numeric "
            "conditions in this snapshot." + detail
        )
        text += "\n" + "\n".join(notes)
        text += "\n" + " ".join(
            format_citation_tag(c, snap.investigations_by_id[c.accession].doi) for c in availability
        )
        return _answer(text.strip(), availability)
    if not available:
        text = (
            "The requested measurements are unavailable in the imported test rows.\n"
            + "\n".join(notes)
        )
        text += "\n" + " ".join(
            format_citation_tag(c, snap.investigations_by_id[c.accession].doi) for c in availability
        )
        return _answer(text.strip(), availability)
    # Prefer rows containing the requested quantities together, never substitute
    # a different quantity merely because it is populated.
    available.sort(
        key=lambda r: (
            -sum(getattr(r, f) is not None for f, _ in requested),
            r.accession,
            r.source_row or 0,
        )
    )
    sample = available[:8]
    citations = cite(snap, [], sample)
    lines = [
        f"{len(rows)} individual source rows match the scope, fuel and numeric filters. "
        f"Showing {len(sample)} cited examples; this is not the complete result list."
    ]
    for row, citation in zip(sample, citations, strict=True):
        values = [
            f"{label}: {getattr(row, field)}"
            if getattr(row, field) is not None
            else f"{label}: not available"
            for field, label in requested
        ]
        lines.append(
            f"- {row.accession} / {row.test_id}; fuel: {row.fuel or 'not reported'}; "
            + "; ".join(values)
            + " "
            + format_citation_tag(citation, snap.investigations_by_id[row.accession].doi)
        )
    lines.extend(notes)
    for c in availability:
        lines.append(format_citation_tag(c, snap.investigations_by_id[c.accession].doi))
    return _answer("\n".join(lines), citations + availability, True)


def document_answer(question, chunks, snap, cite):
    if not re.search(r"\bwhy\b|behavior|phenomena|hypothes|objectives?|findings", question, re.I):
        return None
    generic = {
        "what",
        "were",
        "why",
        "which",
        "does",
        "with",
        "from",
        "according",
        "reported",
        "main",
        "experiments",
        "investigation",
        "behavior",
        "phenomena",
        "findings",
        "the",
        "and",
        "that",
        "than",
        "can",
        "more",
        "was",
    }

    def terms(text):
        return {
            "extinction"
            if re.match(r"extinguish|extinct", word)
            else "droplet"
            if word == "droplets"
            else word
            for word in re.findall(r"[a-z]+", unicodedata.normalize("NFKC", text).casefold())
            if len(word) > 2 and word not in generic
        }

    query = terms(question)
    choices = []
    for chunk in chunks:
        sentences = re.split(r"(?<=[.!?])\s+", " ".join(chunk.text.split()))
        scores = [
            (
                len(query & terms(sentence))
                + (
                    3
                    if re.search(
                        r"observed|showed|exhibited|extinguishes|prolonged|inhibits", sentence, re.I
                    )
                    else 0
                ),
                index,
            )
            for index, sentence in enumerate(sentences)
            if len(sentence) > 45
        ]
        if not scores:
            continue
        score, index = max(scores)
        if score < 2:
            continue
        start = max(0, index - 1)
        if start == 0 and sentences[0][:1].islower():
            start = min(1, index)
        excerpt = " ".join(sentences[start : index + 2])
        if chunk.field_name == "hypothesis" or re.search(
            r"tests? the hypothesis|hypothes", excerpt, re.I
        ):
            label = "Research hypothesis (not an established universal result)"
        elif chunk.field_name == "objectives":
            label = "Research objectives"
        else:
            label = "Source account"
        choices.append((score, chunk, excerpt, label))
    choices.sort(key=lambda item: item[0], reverse=True)
    selected = []
    parts = []
    seen = set()
    for _, chunk, excerpt, label in choices:
        if excerpt in seen:
            continue
        seen.add(excerpt)
        selected.append(chunk)
        parts.append((excerpt, label))
        if len(selected) == 4:
            break
    if not selected:
        return None
    citations = cite(snap, selected, [])
    lines = ["Source-grounded science context:"]
    for chunk, (excerpt, label), citation in zip(selected, parts, citations, strict=True):
        inv = snap.investigations_by_id[chunk.accession]
        lines.append(
            f"- {inv.acronym or inv.accession} / {label}: {excerpt} "
            + format_citation_tag(citation, inv.doi)
        )
    lines.append(
        "Quoted accounts apply to the conditions described in their sources. "
        "Hypotheses and objectives are not presented as certified safety conclusions."
    )
    return _answer("\n".join(lines), citations, True)
