"""Azure OpenAI / OpenAI-compatible wrapper with deterministic offline mode."""

from __future__ import annotations

import hashlib
import json
import logging
import math
import re
from collections.abc import Sequence
from typing import Any, Literal

from openai import AzureOpenAI, OpenAI
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from api.config import Settings
from api.models import Citation, ExperimentalTest, TextChunk

logger = logging.getLogger(__name__)

EMBEDDING_DIM = 128

# 64 domain vocabulary groups for deterministic offline semantic matching.
_DOMAIN_VOCAB_GROUPS: tuple[tuple[str, ...], ...] = (
    ("oxygen", "o2", "xo2", "oxidizer"),
    ("pressure", "kpa", "psi", "atm", "mmhg", "bar"),
    ("flow", "airflow", "velocity", "ventilation", "forced", "quiescent"),
    ("opposed", "counterflow"),
    ("concurrent", "coflow"),
    ("gravity", "microgravity", "0g", "1g"),
    ("lunar", "moon", "partial", "martian", "mars", "reduced"),
    ("iss", "station", "spacecraft", "cabin", "habitat", "rover", "spacesuit"),
    ("solid", "fabric", "fabrics", "cloth", "textile", "sheet", "slab"),
    ("cotton", "cellulose", "sibal", "fiberglass"),
    ("nomex", "ultem", "kevlar", "kapton"),
    ("pmma", "acrylic", "polyethylene", "plastic", "polymer"),
    ("liquid", "droplet", "droplets", "spray", "pool"),
    ("heptane", "octane", "decane", "dodecane", "alkane"),
    ("methanol", "ethanol", "alcohol"),
    ("gas", "gaseous", "methane", "ethane", "propane", "ethylene", "hydrogen"),
    ("burner", "nozzle", "jet", "slot"),
    ("ignited", "ignition", "ignite", "igniter", "kanthal"),
    ("extinguished", "extinguish", "extinction", "quench", "quenching", "blowoff"),
    ("cool", "coolflame", "lowtemperature"),
    ("flame", "flames", "burning", "burn", "combust", "combustion"),
    ("spread", "spreading", "propagation", "rate"),
    ("flammability", "flammable", "limit", "limits", "loc"),
    ("diluent", "inert", "nitrogen", "n2"),
    ("helium", "he"),
    ("co2", "carbon"),
    ("argon", "ar"),
    ("soot", "smoke", "particulate", "aerosol"),
    ("radiation", "radiative", "emission", "radiometer"),
    ("temperature", "thermal", "heat", "pyrolysis"),
    ("diameter", "thickness", "size", "length", "width", "dimension"),
    ("sphere", "cylinder", "rod", "flat", "planar", "sample", "geometry"),
    ("prevention", "prevent", "selection", "material"),
    ("detection", "detect", "detector", "sensor", "sensors"),
    ("suppression", "suppress", "suppressant", "extinguisher", "mist", "water"),
    ("bass", "psi26"),
    ("bassii", "psi25"),
    ("flex", "flex2", "psi69"),
    ("cfi", "cfig", "psi159", "coflow"),
    ("spice", "psi107"),
    ("slice", "saffire", "psi100"),
    ("acme", "efield", "bre", "sflame"),
    ("same", "samer"),
    ("msg", "glovebox", "duct"),
    ("cir", "mdca", "chamber"),
    ("apollo", "mir", "history", "incident", "accident"),
    ("spinoff", "spinoffs", "terrestrial", "earth", "firefighter"),
    ("report", "reports", "paper", "publication", "doi"),
    ("hypothesis", "objective", "objectives", "approach", "method"),
    ("impact", "impacts", "model", "modeling", "validation", "predictive"),
    ("preheat", "preheating", "wake"),
    ("extinctiondiameter", "standoff", "residence"),
    ("mass", "burningrate", "heatrelease", "hrr"),
    ("volume", "mole", "fraction", "percent", "concentration"),
    ("normal", "inverse", "diffusion", "premixed"),
    ("stability", "instability", "oscillation", "oscillating"),
    ("extinctionlimit", "quenchlimit", "blowofflimit"),
    ("safety", "hazard", "risk", "crew"),
    ("filter", "range", "minimum", "maximum", "threshold"),
    ("compare", "comparison", "difference", "similarity"),
    ("hardware", "apparatus", "facility", "platform"),
    ("diagnostics", "camera", "thermocouple", "laser", "imaging"),
    ("nasa", "psi", "informatics", "catalogue", "archive"),
    ("test", "tests", "experiment", "experiments", "trial", "trials"),
)

_TOKEN_TO_BUCKET: dict[str, int] = {}
for _bucket_idx, _terms in enumerate(_DOMAIN_VOCAB_GROUPS):
    for _term in _terms:
        _TOKEN_TO_BUCKET[_term] = _bucket_idx

_ACRONYM_TO_ACCESSION: tuple[tuple[re.Pattern[str], str], ...] = (
    (re.compile(r"\bBASS[\s-]*II\b", re.IGNORECASE), "PSI-25"),
    (re.compile(r"\bBASS\b(?![\s-]*II\b)", re.IGNORECASE), "PSI-26"),
    (re.compile(r"\bFLEX[\s-]*2\b", re.IGNORECASE), "PSI-143"),
    (re.compile(r"\bFLEX\b(?![\s-]*2\b)", re.IGNORECASE), "PSI-69"),
    (re.compile(r"\bCFI[\s-]*G\b", re.IGNORECASE), "PSI-159"),
    (re.compile(r"\bSPICE\b", re.IGNORECASE), "PSI-107"),
    (re.compile(r"\bSAFFIRE(?:[\s-]*III)?\b", re.IGNORECASE), "PSI-100"),
)

_SPECIFIC_FUELS: tuple[str, ...] = (
    "cotton",
    "pmma",
    "nomex",
    "ultem",
    "heptane",
    "methanol",
    "decane",
    "dodecane",
    "octane",
    "methane",
    "propane",
    "ethylene",
    "ethanol",
    "cellulose",
    "fiberglass",
)


class SqlRowFilter(BaseModel):
    """Structured SQL filter proposed for querying tests.parquet."""

    model_config = ConfigDict(extra="ignore")

    accessions: list[str] = Field(default_factory=list)
    fuel: str | None = None
    fuel_phase: Literal["solid", "liquid", "gas", "mixed", "unknown"] | None = None
    o2_min: float | None = Field(default=None, ge=0, le=1)
    o2_max: float | None = Field(default=None, ge=0, le=1)
    pressure_min: float | None = Field(default=None, gt=0)
    pressure_max: float | None = Field(default=None, gt=0)
    flow_min: float | None = Field(default=None, ge=0)
    flow_max: float | None = Field(default=None, ge=0)
    diluent: str | None = None
    outcome: Literal["ignited", "extinguished", "cool_flame", "failed", "unknown"] | None = None
    limit: int = Field(default=25, ge=1, le=100)


def cosine_similarity(vec_a: Sequence[float], vec_b: Sequence[float]) -> float:
    """Compute cosine similarity between two equal-length vectors."""
    if not vec_a or not vec_b or len(vec_a) != len(vec_b):
        return 0.0
    dot = sum(a * b for a, b in zip(vec_a, vec_b, strict=True))
    norm_a = math.sqrt(sum(a * a for a in vec_a))
    norm_b = math.sqrt(sum(b * b for b in vec_b))
    if norm_a == 0.0 or norm_b == 0.0:
        return 0.0
    return dot / (norm_a * norm_b)


def deterministic_embed(text: str) -> list[float]:
    """Build a deterministic 128-dim L2-normalized vector without network calls."""
    vector = [0.0] * EMBEDDING_DIM
    tokens = re.findall(r"[a-z0-9]+", text.casefold())
    if not tokens:
        return vector

    for token in tokens:
        if len(token) < 2 and token not in {"o", "g"}:
            continue
        bucket = _TOKEN_TO_BUCKET.get(token)
        if bucket is not None:
            vector[bucket] += 2.0
        digest = hashlib.sha256(token.encode("utf-8")).digest()
        hash_bucket = 64 + (int.from_bytes(digest[:4], "big") % 64)
        sign = 1.0 if (digest[4] & 1) == 0 else -1.0
        vector[hash_bucket] += sign

    # Include adjacent token bigrams in hash space to preserve short-phrase similarity.
    for left, right in zip(tokens, tokens[1:], strict=False):
        bigram = f"{left}_{right}"
        digest = hashlib.sha256(bigram.encode("utf-8")).digest()
        hash_bucket = 64 + (int.from_bytes(digest[:4], "big") % 64)
        sign = 1.0 if (digest[4] & 1) == 0 else -1.0
        vector[hash_bucket] += 0.75 * sign

    norm = math.sqrt(sum(v * v for v in vector))
    if norm == 0.0:
        return vector
    return [v / norm for v in vector]


def _normalize_o2_value(raw_value: float, has_percent: bool) -> float:
    value = raw_value / 100.0 if (has_percent or raw_value > 1.0) else raw_value
    return max(0.0, min(1.0, value))


def _normalize_pressure_kpa(raw_value: float, unit: str) -> float:
    unit_lower = unit.casefold()
    if unit_lower == "atm":
        return raw_value * 101.325
    if unit_lower == "psi":
        return raw_value * 6.894757293168
    if unit_lower == "bar":
        return raw_value * 100.0
    if unit_lower == "mmhg":
        return raw_value * 0.1333223684
    return raw_value


def deterministic_sql_filter(
    question: str,
    investigation_ids: list[str] | None = None,
) -> SqlRowFilter:
    """Extract conservative structured test-table filters from natural language."""
    accessions: list[str] = []
    for accession in investigation_ids or []:
        if accession not in accessions:
            accessions.append(accession)
    for match in re.findall(r"\bPSI-\d+\b", question, flags=re.IGNORECASE):
        canonical = match.upper()
        if canonical not in accessions:
            accessions.append(canonical)
    if not investigation_ids:
        for pattern, accession in _ACRONYM_TO_ACCESSION:
            if pattern.search(question) and accession not in accessions:
                accessions.append(accession)

    q_lower = question.casefold()

    fuel: str | None = None
    for candidate in _SPECIFIC_FUELS:
        if re.search(rf"\b{re.escape(candidate)}\b", q_lower):
            fuel = candidate
            break

    fuel_phase: Literal["solid", "liquid", "gas", "mixed", "unknown"] | None = None
    if re.search(r"\b(?:solid|fabrics?|cotton|pmma|plastics?|nomex|ultem|cloth)\b", q_lower):
        fuel_phase = "solid"
    elif re.search(r"\b(?:liquid|droplets?|heptane|methanol|decane|ethanol)\b", q_lower):
        fuel_phase = "liquid"
    elif re.search(r"\b(?:gaseous|gas\s+flames?|methane|propane|ethylene|burner)\b", q_lower):
        fuel_phase = "gas"

    o2_min: float | None = None
    o2_max: float | None = None
    for match in re.finditer(
        r"\b(above|over|greater than|more than|at least|>=|>|below|under|less than|at most|<=|<)\s*"
        r"(\d+(?:\.\d+)?)\s*(%|percent)?\s*(?:o2|oxygen)\b",
        q_lower,
    ):
        op, num_str, pct = match.groups()
        val = _normalize_o2_value(float(num_str), bool(pct))
        if op in {"above", "over", "greater than", "more than", "at least", ">=", ">"}:
            o2_min = val if o2_min is None else max(o2_min, val)
        else:
            o2_max = val if o2_max is None else min(o2_max, val)

    for match in re.finditer(
        r"\b(?:o2|oxygen)\s*(?:>=|>|above|at least)\s*(\d+(?:\.\d+)?)\s*(%|percent)?\b",
        q_lower,
    ):
        val = _normalize_o2_value(float(match.group(1)), bool(match.group(2)))
        o2_min = val if o2_min is None else max(o2_min, val)

    for match in re.finditer(
        r"\b(?:o2|oxygen)\s*(?:<=|<|below|under|at most)\s*(\d+(?:\.\d+)?)\s*(%|percent)?\b",
        q_lower,
    ):
        val = _normalize_o2_value(float(match.group(1)), bool(match.group(2)))
        o2_max = val if o2_max is None else min(o2_max, val)

    if o2_min is not None and o2_max is not None and o2_min > o2_max:
        o2_min, o2_max = None, None

    pressure_min: float | None = None
    pressure_max: float | None = None
    for match in re.finditer(
        r"\b(above|over|greater than|more than|at least|>=|>|below|under|less than|at most|<=|<)\s*"
        r"(\d+(?:\.\d+)?)\s*(kpa|atm|psi|bar|mmhg)\b",
        q_lower,
    ):
        op, num_str, unit = match.groups()
        val = _normalize_pressure_kpa(float(num_str), unit)
        if val <= 0:
            continue
        if op in {"above", "over", "greater than", "more than", "at least", ">=", ">"}:
            pressure_min = val if pressure_min is None else max(pressure_min, val)
        else:
            pressure_max = val if pressure_max is None else min(pressure_max, val)

    if pressure_min is not None and pressure_max is not None and pressure_min > pressure_max:
        pressure_min, pressure_max = None, None

    flow_min: float | None = None
    flow_max: float | None = None
    for match in re.finditer(
        r"\b(above|over|greater than|more than|at least|>=|>|below|under|less than|at most|<=|<)\s*"
        r"(\d+(?:\.\d+)?)\s*cm/s\b",
        q_lower,
    ):
        op, num_str = match.groups()
        val = float(num_str)
        if op in {"above", "over", "greater than", "more than", "at least", ">=", ">"}:
            flow_min = val if flow_min is None else max(flow_min, val)
        else:
            flow_max = val if flow_max is None else min(flow_max, val)

    if flow_min is not None and flow_max is not None and flow_min > flow_max:
        flow_min, flow_max = None, None

    diluent: str | None = None
    if re.search(r"\bhelium\b", q_lower):
        diluent = "He"
    elif re.search(r"\b(?:nitrogen|n2)\b", q_lower):
        diluent = "N2"
    elif re.search(r"\b(?:carbon\s+dioxide|co2)\b", q_lower):
        diluent = "CO2"

    outcome: Literal["ignited", "extinguished", "cool_flame", "failed", "unknown"] | None = None
    if re.search(r"\bcool[\s-]+flames?\b", q_lower):
        outcome = "cool_flame"
    elif re.search(r"\bextinguish(?:ed|ment|ing)?\b", q_lower):
        outcome = "extinguished"
    elif re.search(r"\b(?:ignit(?:ed|ion)|burned)\b", q_lower):
        outcome = "ignited"

    return SqlRowFilter(
        accessions=accessions,
        fuel=fuel,
        fuel_phase=fuel_phase,
        o2_min=o2_min,
        o2_max=o2_max,
        pressure_min=pressure_min,
        pressure_max=pressure_max,
        flow_min=flow_min,
        flow_max=flow_max,
        diluent=diluent,
        outcome=outcome,
    )


def format_citation_tag(citation: Citation, doi: str | None = None) -> str:
    """Format an inline citation tag matching [PSI-XX, DOI, locator]."""
    doi_part = doi or "no-doi"
    return f"[{citation.accession}, {doi_part}, {citation.locator}]"


def _format_row_summary(row: ExperimentalTest, citation_tag: str) -> str:
    parts: list[str] = [f"test {row.test_id}"]
    if row.fuel:
        parts.append(f"fuel={row.fuel}")
    if row.o2_fraction is not None:
        parts.append(f"O2={row.o2_fraction * 100:.1f}%")
    if row.pressure_kpa is not None:
        parts.append(f"P={row.pressure_kpa:.2f} kPa")
    if row.flow_cm_s is not None:
        parts.append(f"flow={row.flow_cm_s:.1f} cm/s")
    if row.diluent:
        parts.append(f"diluent={row.diluent}")
    if row.outcome:
        parts.append(f"outcome={row.outcome}")
    return f"{', '.join(parts)} {citation_tag}"


def _partial_gravity_requested(question: str) -> bool:
    return bool(
        re.search(
            r"\b(?:partial[\s-]*g|partial\s+gravity|reduced\s+gravity|lunar|moon|mars|martian|0\.16\s*g|1/6\s*g)\b",
            question.casefold(),
        )
    )


def deterministic_grounded_answer(
    question: str,
    chunks: list[TextChunk],
    rows: list[ExperimentalTest],
    citations: list[Citation],
    *,
    doi_by_accession: dict[str, str | None] | None = None,
) -> str:
    """Construct a deterministic citation-backed answer strictly from retrieved evidence."""
    doi_map = doi_by_accession or {}
    chunk_tags: list[tuple[TextChunk, str]] = []
    row_tags: list[tuple[ExperimentalTest, str]] = []

    citation_by_chunk_id: dict[str, Citation] = {}
    citation_by_row_key: dict[tuple[str, int | None, str], Citation] = {}
    for citation in citations:
        if citation.id.startswith("chunk:"):
            citation_by_chunk_id[citation.id.removeprefix("chunk:")] = citation
        elif citation.id.startswith("row:"):
            key = (
                citation.accession,
                citation.provenance.source_row,
                citation.provenance.source_file,
            )
            citation_by_row_key[key] = citation

    for chunk in chunks[:4]:
        cit = citation_by_chunk_id.get(chunk.chunk_id)
        if cit is None:
            continue
        doi = chunk.doi or doi_map.get(cit.accession)
        chunk_tags.append((chunk, format_citation_tag(cit, doi)))

    for row in rows[:5]:
        key = (row.accession, row.source_row, row.source_file or row.provenance.source_file)
        cit = citation_by_row_key.get(key)
        if cit is None:
            continue
        doi = row.doi or doi_map.get(row.accession)
        row_tags.append((row, format_citation_tag(cit, doi)))

    sections: list[str] = []
    if chunk_tags:
        excerpts = []
        for chunk, tag in chunk_tags:
            snippet = " ".join(chunk.text.strip().split())
            if len(snippet) > 220:
                snippet = snippet[:217].rstrip() + "..."
            excerpts.append(f"- {snippet} {tag}")
        sections.append("Retrieved PSI evidence:\n" + "\n".join(excerpts))

    if row_tags:
        row_lines = [f"- {_format_row_summary(row, tag)}" for row, tag in row_tags]
        sections.append("Matching normalized test rows:\n" + "\n".join(row_lines))

    if _partial_gravity_requested(question):
        sections.append(
            "Gap notice: NASA PSI contains no partial-gravity (lunar or Martian) combustion test "
            "measurements; only normal-gravity (1g) and microgravity bounds are available."
        )

    if not sections and citations:
        first = citations[0]
        sections.append(
            f"Evidence retrieved for {first.accession}: {first.supporting_text} "
            f"{format_citation_tag(first, doi_map.get(first.accession))}"
        )

    return "\n\n".join(sections)


def _strip_json_fences(raw: str) -> str:
    """Strip optional Markdown code fences around a JSON object response."""
    stripped = raw.strip()
    if stripped.startswith("```"):
        stripped = re.sub(r"^```(?:json)?\s*", "", stripped, flags=re.IGNORECASE)
        stripped = re.sub(r"\s*```$", "", stripped)
    return stripped.strip()


class LLMClient:
    """Wrapper over OpenRouter, Azure OpenAI, and OpenAI-compatible SDKs with offline fallback."""

    def __init__(self, settings: Settings | None = None, openai_client: Any = None) -> None:
        self.settings = settings or Settings()
        self._injected_client = openai_client
        self._client: Any = openai_client

    @property
    def provider(self) -> Literal["offline", "openrouter", "azure", "injected"]:
        if self.settings.mode == "mock" or self.settings.llm_provider == "offline":
            return "offline"
        if self._injected_client is not None:
            return "injected"

        pref = self.settings.llm_provider
        has_openrouter = bool(self.settings.openrouter_api_key.strip())
        has_azure = bool(
            self.settings.azure_openai_endpoint.strip()
            and self.settings.azure_openai_api_key.strip()
        )
        if pref == "openrouter":
            return "openrouter" if has_openrouter else "offline"
        if pref == "azure":
            return "azure" if has_azure else "offline"
        if has_openrouter:
            return "openrouter"
        if has_azure:
            return "azure"
        return "offline"

    @property
    def is_live(self) -> bool:
        return self.provider != "offline"

    @property
    def chat_model(self) -> str:
        if self.provider == "openrouter":
            return self.settings.openrouter_model
        return self.settings.azure_openai_chat_deployment

    def _get_client(self) -> Any:
        if self._client is not None:
            return self._client
        if self.provider == "openrouter":
            self._client = OpenAI(
                base_url=self.settings.openrouter_base_url.strip(),
                api_key=self.settings.openrouter_api_key.strip(),
                default_headers={
                    "HTTP-Referer": "https://github.com/talhaadil48/firelens",
                    "X-Title": "FireLens",
                },
            )
            return self._client

        endpoint = self.settings.azure_openai_endpoint.strip()
        api_key = self.settings.azure_openai_api_key.strip()
        if "openai.azure.com" in endpoint or "cognitiveservices.azure.com" in endpoint:
            self._client = AzureOpenAI(
                azure_endpoint=endpoint,
                api_key=api_key,
                api_version=self.settings.azure_openai_api_version,
            )
        else:
            self._client = OpenAI(
                base_url=endpoint,
                api_key=api_key,
            )
        return self._client

    def embed_texts(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []
        provider = self.provider
        if provider in {"offline", "openrouter"} or (provider != "injected" and len(texts) > 128):
            return [deterministic_embed(text) for text in texts]
        try:
            client = self._get_client()
            response = client.embeddings.create(
                model=self.settings.azure_openai_embedding_deployment,
                input=texts,
            )
            data = sorted(response.data, key=lambda item: getattr(item, "index", 0))
            vectors = [list(item.embedding) for item in data]
            if len(vectors) == len(texts):
                return vectors
        except Exception as exc:
            logger.warning(
                "Embedding call failed (%s); falling back to deterministic offline embeddings.",
                type(exc).__name__,
            )
        return [deterministic_embed(text) for text in texts]

    def embed_text(self, text: str) -> list[float]:
        return self.embed_texts([text])[0]

    def propose_sql_filter(
        self,
        question: str,
        investigation_ids: list[str] | None = None,
    ) -> SqlRowFilter:
        baseline = deterministic_sql_filter(question, investigation_ids)
        if not self.is_live:
            return baseline

        system_prompt = (
            "Extract a JSON filter for NASA PSI combustion test rows matching the user's question. "
            "Allowed keys: accessions (list of PSI-N strings), fuel, fuel_phase "
            "(solid|liquid|gas|mixed|unknown), o2_min (0..1), o2_max (0..1), "
            "pressure_min (kPa > 0), pressure_max (kPa > 0), flow_min (cm/s >= 0), "
            "flow_max (cm/s >= 0), diluent (N2|He|CO2), outcome "
            "(ignited|extinguished|cool_flame|failed|unknown), limit (1..100). "
            "Return only valid JSON with null for unspecified fields."
        )
        try:
            client = self._get_client()
            response = client.chat.completions.create(
                model=self.chat_model,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": question},
                ],
                temperature=0,
                response_format={"type": "json_object"},
            )
            content = _strip_json_fences(response.choices[0].message.content or "{}")
            parsed = SqlRowFilter.model_validate(json.loads(content))
            merged_accessions = list(
                dict.fromkeys(
                    [*(investigation_ids or []), *parsed.accessions, *baseline.accessions]
                )
            )
            return SqlRowFilter(
                accessions=merged_accessions,
                fuel=parsed.fuel or baseline.fuel,
                fuel_phase=parsed.fuel_phase or baseline.fuel_phase,
                o2_min=parsed.o2_min if parsed.o2_min is not None else baseline.o2_min,
                o2_max=parsed.o2_max if parsed.o2_max is not None else baseline.o2_max,
                pressure_min=(
                    parsed.pressure_min
                    if parsed.pressure_min is not None
                    else baseline.pressure_min
                ),
                pressure_max=(
                    parsed.pressure_max
                    if parsed.pressure_max is not None
                    else baseline.pressure_max
                ),
                flow_min=parsed.flow_min if parsed.flow_min is not None else baseline.flow_min,
                flow_max=parsed.flow_max if parsed.flow_max is not None else baseline.flow_max,
                diluent=parsed.diluent or baseline.diluent,
                outcome=parsed.outcome or baseline.outcome,
                limit=parsed.limit,
            )
        except (ValidationError, ValueError, KeyError, IndexError, TypeError) as exc:
            logger.warning(
                "Structured filter parsing failed (%s); using deterministic SQL filter.",
                type(exc).__name__,
            )
            return baseline
        except Exception as exc:
            logger.warning(
                "Live filter proposal failed (%s); using deterministic SQL filter.",
                type(exc).__name__,
            )
            return baseline

    def generate_grounded_answer(
        self,
        question: str,
        chunks: list[TextChunk],
        rows: list[ExperimentalTest],
        citations: list[Citation],
        *,
        doi_by_accession: dict[str, str | None] | None = None,
    ) -> str:
        fallback = deterministic_grounded_answer(
            question, chunks, rows, citations, doi_by_accession=doi_by_accession
        )
        if not self.is_live:
            return fallback

        doi_map = doi_by_accession or {}
        evidence_blocks: list[str] = []
        for idx, chunk in enumerate(chunks, start=1):
            doi = chunk.doi or doi_map.get(chunk.accession or "") or "no-doi"
            page_str = f" p.{chunk.page}" if chunk.page else ""
            evidence_blocks.append(
                f"[Chunk {idx}] [{chunk.accession}, {doi}, {chunk.source_file}{page_str}]: "
                f"{chunk.text}"
            )
        for idx, row in enumerate(rows, start=1):
            doi = row.doi or doi_map.get(row.accession) or "no-doi"
            src_file = row.source_file or row.provenance.source_file
            evidence_blocks.append(
                f"[Row {idx}] [{row.accession}, {doi}, {src_file} row {row.source_row}]: "
                f"test_id={row.test_id}, fuel={row.fuel}, fuel_phase={row.fuel_phase}, "
                f"o2_fraction={row.o2_fraction}, pressure_kpa={row.pressure_kpa}, "
                f"flow_cm_s={row.flow_cm_s}, diluent={row.diluent}, outcome={row.outcome}"
            )

        system_prompt = (
            "You are FireLens, a scientific assistant for NASA PSI microgravity combustion data. "
            "Answer ONLY using the provided evidence blocks. Every claim or number MUST include "
            "an inline citation in the exact format [PSI-XX, DOI, locator] copied from the blocks. "
            "Never invent measurements, citations, safety approvals, or partial-gravity data. "
            "If partial gravity is asked about, state explicitly that PSI has no partial-gravity "
            "measurements yet."
        )
        user_prompt = f"Question: {question}\n\nEvidence:\n" + "\n".join(evidence_blocks)

        try:
            client = self._get_client()
            response = client.chat.completions.create(
                model=self.chat_model,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
                temperature=0.1,
            )
            text = (response.choices[0].message.content or "").strip()
            if text and any(c.accession in text for c in citations):
                return text
        except Exception as exc:
            logger.warning(
                "Chat generation failed (%s); falling back to deterministic grounded synthesis.",
                type(exc).__name__,
            )
        return fallback
