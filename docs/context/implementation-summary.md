> Historical derived summary. Superseded as the primary product reference by
> the complete supplied `flame-in-freefall-plan.md`. Read `PLAN_ALIGNMENT.md`
> for the current implementation assessment.

# FireLens — product and implementation context

## Document status

This plan is a synthesis of the owner's supplied `build-steps.md` and
`reference/dashboard-ui-concept.html`, added to make the intended product clear
for future contributors. It does not replace the original checklist or claim
that its demonstration values have been scientifically verified.

The latest authorized implementation milestone is Phase 3 collection on its own branch.
This document describes later work without authorizing deployment, spending,
automatic data updates or additional implementation phases.

## The product in simple language

FireLens helps researchers find and compare NASA microgravity combustion
research, understand experimental conditions, and trace answers to evidence.
Its central question is: what do the collected studies tell us about a selected
research scenario, and what evidence is missing from this collection?

The intended result is research support, not a validated mission-safety predictor
or a system for approving spacecraft materials.

## Intended experience

1. Select an illustrative mission profile or enter conditions.
2. Find relevant investigations and understand the ranking rationale.
3. Inspect what was tested and open supporting source documents or rows.
4. Compare investigations while seeing important differences and missing fields.
5. Ask a question and inspect the passages and rows supporting the answer.
6. Export selected data with citations and original source locations.

## Four screens in the owner's HTML reference

### Mission Explorer

Mission-profile controls, oxygen/pressure/airflow/gravity readouts, ranked
investigation cards, prevention/detection/suppression filters, a condition
coverage map with a scenario envelope, and evidence gaps/cautions. Data freshness
and update counts must come from an actual check, not hardcoded labels.

### Investigation detail

Investigation identity, source version and license, reviewed summary, tested
materials and hardware, original experimental rows, source files, publications,
related investigations, DOI/source links and copyable dataset citations.

### Compare investigations

Two or three investigations side by side, highlighted differences, and a
same/different explanation grounded in displayed source fields. Different fuel
phases, geometry, gravity or measured quantities must remain visible.

### Ask FireLens

A source-linked answer with relevant conditions and uncertainty, supporting
passages, original row references, structured-filter trace, suggested questions
and export/copy actions. Without supporting evidence, say so explicitly.

## Data flow

NASA PSI catalogue and manifests → original experimental tables/documents →
reviewed mapping rules → validated normalized tests → frozen snapshot →
search/filter/relevance API → dashboard and evidence-grounded explanations.

- Keep documents, investigation metadata, test rows and findings distinguishable.
- Preserve original files, source version, hashes, units and row/page locations.
- Do not infer independent test counts from raw CSV record counts.
- Missing values stay null; ranges and multi-value cells need reviewed mapping.
- Never copy investigation-wide bounds onto individual test rows as measured values.
- Separate experimental measurements, simulations, authors' explanations and inference.
- Exclude mock/unreviewed measurements from scientific coverage and conclusions.

## Sources and first scope

PSI is the primary investigation/data source. NTRS can provide supporting papers.
The initial fixture set contains BASS (PSI-26), BASS-II (PSI-25), FLEX (PSI-69),
CFI-G (PSI-159) and Saffire-III (PSI-100). This is not the full collection.
Source/DOI links, reuse terms and any scientific statements require verification.
The Phase 2 spike downloads FLEX and both CFI-G experimental CSVs.

## Stack and responsibilities

- `harvest/`: source downloads, then later reviewed normalization/precomputation.
- `api/`: shared Pydantic models and FastAPI contracts; later real query/retrieval logic.
- `web/`: Vite, React, TypeScript, Tailwind and Plotly user interface.
- `config/`: explicit mission assumptions and draft ranking configuration.
- `snapshots/`: frozen reproducible data; only a sample is committed.
- `tests/`: software/data invariants and contract checks.
- `sync/` and `infra/`: later update/deployment work; presently scaffolding.
- `docs/` and `scripts/`: evidence, handoffs and reproducible developer tasks.

## Differences that must be resolved before real ranking

The HTML defines the weights as:

| Dimension | Weight |
| --- | --- |
| Conditions match | 0.40 |
| Fuel realism | 0.25 |
| Safety goal | 0.20 |
| Data richness | 0.15 |

The current Phase 2 config provisionally assigns the same numbers to oxygen,
pressure, airflow and gravity. These are different scoring systems. Do not claim
that they match. Confirm the intended formula, field definitions, treatment of
missing data and scientific rationale before implementing real scores. If the
HTML approach is selected, update Python/TypeScript contracts, config, fixtures,
labels and tests together. A relevance score is not a probability of safety.

The HTML also supplies rover conditions and approximate airflow/gravity values
that the current config leaves unspecified. Its plotted scenario envelopes are
not always identical to its text labels. Confirm the authoritative scenario
values and document their sources or label them illustrative. No scenario is an
approved NASA mission specification by default.

The reference uses different profile identifiers (`moon`, `suit`) from the API
(`moon_base`, `spacesuit`). Map these explicitly rather than creating duplicate profiles.

## Current implementation boundary

Implemented: project scaffold, source spike, shared data validation, API/SSE
contracts, five real-metadata fixtures, illustrative profiles, basic web preview
and CI. The API deliberately returns no scientific scores, no normalized test
rows and an insufficient-evidence chat response.

Phase 3 adds the full-catalogue collector and raw-file audit; see the Phase 3 handoff
for actual collection results and unresolved source links.

Not yet implemented: normalization, reviewed scientific findings,
real relevance ranking, populated coverage map, live grounded AI, all four final
screens, production sync or cloud deployment. See the handoff for test evidence.

## How progress should be judged

Use the original build checklist for phase acceptance. Independently verify that
claims match passages, numerical values retain units/baselines, comparisons show
important differences, and unsupported questions receive an honest abstention.
Keep the submitted dataset/version stable and state which findings were reviewed.
