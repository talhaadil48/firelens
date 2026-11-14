# Complete plan versus current implementation

Reviewed on 14 November 2026 against the owner's newly supplied complete
`flame-in-freefall-plan.md`. This compares the repository with the document; it
is not independent verification of the plan's external scientific, pricing,
account-offer or event-rule claims.

## Overall assessment

**The implemented Phase 1–3 foundation broadly follows the plan. It is not a full
or exact implementation of the complete product.** The harvester, provenance,
raw-data limits, stack and mock contracts are suitable foundations. Before
normalization and real ranking, align the shared schema and score definitions.

`flame-in-freefall-plan.md` is now the primary supplied product plan. The earlier
assistant-derived summary is preserved as `implementation-summary.md` for history.
The original build checklist still describes implementation phases; handoffs and
executed reports describe what actually works.

## Implemented and aligned

| Area | Current implementation | Assessment |
| --- | --- | --- |
| Stack and folders | Python 3.12, httpx, Pandera, FastAPI, React/Vite/TypeScript/Tailwind/Plotly, Docker scaffolds, CI | Aligned foundation; cloud deployment is later work |
| PSI catalogue | Paginates all PSI investigations, then filters exact Combustion Science | Meets the collection intent and avoids relying on a keyword result count |
| Manifests | Stores original JSON, DOI, version, license, hardware and file lists | Aligned |
| Experimental CSVs | Resolves signed links immediately; retains exact bytes, encoding, source versions and hashes | Aligned |
| Download policy | Reports/Science Documents below 20 MB; bulk Raw Data excluded | Aligned with the detailed pipeline and build checklist |
| Caching and concurrency | Three/four workers, retries/backoff, verified on-disk cache, dated archives and failure logs | Aligned |
| Provenance and uncertainty | Nested provenance, source rows/pages, review status, evidence type and uncertainty labels | Consistent with the evidence-first requirement |
| API contracts | All planned route families plus `/meta` and `/profiles`; SSE payload definitions and generated TypeScript | Contract foundation only; scientific responses remain mocks |
| Final UI direction | Explorer, coverage, investigation detail, compare, chat and export are represented in the plan/reference | Only the basic preview is implemented so far |

## Differences requiring implementation work

### 1. The unified row schema is only partially aligned

Current contracts are in `api/models.py`. The supplied plan now gives details
that were unavailable when the provisional contract was written.

| Complete-plan field | Current equivalent/status | Required follow-up |
| --- | --- | --- |
| `accession`, `test_id` | Present | Keep stable IDs and source rows |
| `investigation` | Title is in the investigation record, joined by accession | Define whether normalized rows also carry a label |
| `test_date` | Missing | Add a nullable date with reviewed date/day-of-year conversion |
| `fuel` | Currently `material` | Define a canonical name or explicit adapter; do not silently drop it |
| `fuel_phase` | Present, including unknown/mixed states | Preserve uncertainty |
| `sample_geometry` | Currently `geometry` | Define the field mapping |
| `sample_size_mm` | Only `thickness_mm` exists | Add representation for diameter/width/length and their original units/provenance |
| `o2_fraction` | Currently `oxygen_fraction` | Define one canonical name or adapter; preserve mole/volume/mass basis |
| `pressure_kpa`, flow fields | Present | Implement reviewed conversions in Phase 4 |
| `diluent` | Missing | Add composition representation; missing fractions must stay missing |
| `outcome` | Present as unrestricted text | Implement reviewed controlled labels without conflating ignition/extinction events |
| `metrics` | Only one `outcome_value`/`outcome_unit` pair exists | Support multiple named metrics with units and source locations |
| `source_file`, `source_row` | Present inside `provenance` | Document flattening for exports |
| `doi` per row/export | Available at investigation/source level; not a row/export field | Join reliably by accession and include it in exports |

Investigation records already include titles, DOI, hardware, platform, fuel phase,
related investigations, condition ranges, findings and source documents. Dedicated
sub-area, objective/approach/hypothesis/impacts, sensors, full publication metadata
and aggregate file-size/count fields are not yet exposed in the API record. The
raw manifests retain the upstream fields for later mapping; metadata was not lost.

When implementing this work, change Pydantic/Pandera models, generated OpenAPI,
TypeScript declarations, fixtures and consumers together. Do not force raw ranges
or multi-value cells into fictional independent scalar tests.

### 2. Ranking dimensions must follow the complete plan

The intended formula is now explicit:

- Conditions match: 0.40
- Fuel realism: 0.25
- Safety-goal match: 0.20
- Data richness: 0.15

The current `RankWeights` and `config/profiles.yaml` instead assign these numbers
to oxygen, pressure, airflow and gravity. That was a provisional choice before
the complete plan was supplied. It is not the same formula. Replace the draft
configuration/contracts when real ranking is implemented; define tolerances,
missing-data treatment and each component's scientific rationale. The current
API returns null scores, so no incorrect numeric ranking is being served.

### 3. Mission profiles need a coordinated update

The complete plan specifies Moon-base AND rover atmospheric scenarios and a
custom profile. The current rover values are unset and there is no complete
editable custom-profile workflow. Current pressure presets also use rounded kPa
values rather than exact conversions of the plan's psi values. Shared weights,
profile inputs, gravity representation and UI controls must be made consistent.
Keep these as sourced scenarios/assumptions rather than certified NASA requirements.

### 4. The exact requested context resources are not all captured

The collector saved six topic sources, including a wool-mask Spinoff article.
The complete plan instead names these three particular Spinoff pages:

- Fireman's air tanks: https://spinoff.nasa.gov/node/9582
- Fire detector: https://spinoff.nasa.gov/node/9407
- Fire attire: https://spinoff.nasa.gov/node/9918

Those three URLs are not currently in `config/context_sources.yaml`. The Apollo
sources also use different primary NASA pages from the plan's SMA lessons-learned
URLs. Add the explicitly requested sources to the context corpus when extending
collection. Do not claim the existing six topics are the exact complete source list.
The official challenge resource page was unreachable during the recorded harvest.

## Observed source differences, rather than implementation defects

- Actual collection: 133 PSI catalogue investigations, 24 labelled Combustion
  Science, 24 manifests, 22 experimental CSVs and 53 supporting documents. The
  plan's approximate counts are not authoritative current inventory numbers.
- Four investigations list no experimental table; none was fabricated.
- Two legacy PSI-26 report entries returned 404. File integrity checks pass, but
  the aggregate collection is explicitly partial. See `../harvest/report.json`.
- Raw CSV record counts include possible headers/descriptions/blank rows. The
  plan's 2,400+ test-row claim must be validated after normalization before display.

## Planned later phases, not features that already exist

Normalization/maps, reviewed summaries, report/DOCX extraction with page-aware
chunks, embeddings, DuckDB/Parquet queries, real relevance scores, grounded AI,
full four-screen dashboard, exports of normalized data, related-study similarity,
cloud hosting, freshness checks and nightly sync remain future implementation.
Only the Researcher's Guide/context text is currently extracted; the 53 collected
supporting documents are not yet a validated searchable text corpus.

The storage description is consistent when read as: originals are local ingestion
inputs, while the deployed snapshot contains reviewed data/text/vectors and users
open upstream source links. Do not package raw video or automatically serve original
report PDFs as part of the public app.

## Claims to verify before presenting

Preserving the supplied plan does not establish the current accuracy of its event
dates, judging interpretation, model prices, offers, available gravity datasets,
future mission status or habitat assumptions. The plan itself alternates between
seven slides OR a 30-second demo and a required slide deck; resolve submission
requirements against the actual event guidance. Scientific claims need direct,
condition-specific evidence rather than being copied from planning prose.

## Recommended implementation order

1. Agree and implement the complete normalized schema, with explicit compatibility
   mappings for the existing API names.
2. Normalize and review priority tables; preserve per-test versus study-wide values.
3. Add the plan's exact missing context references and extract reviewed evidence.
4. Build the snapshot and intended C/F/M/D ranking model.
5. Complete real API behavior, final UI, validation, deployment and submission work.

This review authorizes no additional implementation phase by itself. Follow the
owner's active task instructions; this update changes documentation, not runtime behavior.
