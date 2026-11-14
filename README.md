# FireLens

Evidence-linked exploration of NASA microgravity combustion research.

**Status: Phases 1–2 foundation plus Phase 3 harvest implementation.** This repository contains a reproducible source
spike, shared data models, API contracts, offline fixtures and a React scaffold.
It is not yet the complete research dashboard. The preview uses five real NASA
catalogue records, zero normalized measurements and no live LLM. Null relevance
scores and an empty coverage map are intentional.

## Start locally

Prerequisites: Git, [uv](https://docs.astral.sh/uv/), Python 3.12 (uv can install it),
Node.js 22.13+ (use `.nvmrc`; Node 24 also works), npm, and optionally GNU Make.

```bash
uv sync --frozen
cd web
npm ci
cd ..
```

In two terminals:

```bash
make api     # http://127.0.0.1:8000/docs — offline contract server
make web     # http://127.0.0.1:5173 — offline fixtures by default
```

Without Make: `uv run uvicorn api.main:app --reload` and `cd web && npm run dev`.
To test the UI against the API, copy `web/.env.example` to `web/.env.local`, set
`VITE_DATA_MODE=api`, and restart Vite. No API keys or cloud accounts are required.

## Harvest the full combustion collection (Phase 3)

```bash
uv run python -m harvest.run
# or: make harvest
```

This paginates the PSI catalogue, filters Combustion Science, saves every manifest
and listed experimental CSV, and collects Reports/Science Documents below 20 MB.
It also saves eight NASA context topics as source-linked text. Bulk Raw Data is skipped.
Run folders and cache stay under ignored `raw/`. No API key is required.

A partial run exits nonzero and records failures in its `HARVEST_LOG.md`. The
observed run has 24 manifests, 22 CSVs and 53 supporting documents; two legacy
NASA report URLs returned 404, so it is honestly labelled partial. The API/UI
remain Phase 2 fixtures until normalization and reviewed snapshots exist.
See [Phase 3 handoff](docs/PHASE_3_HANDOFF.md) and [harvest log](docs/harvest/HARVEST_LOG.md).

## Check NASA access (small Phase 2 spike)

```bash
make spike
# or: uv run python -m harvest.spike
```

The spike reads the public PSI catalogue and FLEX (PSI-69) / CFI-G (PSI-159)
manifest records, resolves temporary download URLs and immediately fetches their
experimental CSV files. Original files go to ignored `raw/spike/`; the shareable
report is `docs/SPIKE_RESULTS.json`. Signed URLs are never logged or committed.
Network access is needed only for this explicit check, not normal tests or the preview.

## Checks and generated files

```bash
make lint
make test
make contracts
cd web && npm run generate:types
```

CI runs Python lint/tests, contract-drift checks, web lint/tests and a production
build. OpenAPI and SSE payloads: [`docs/contracts/`](docs/contracts/).
The web team can use [`web/public/fixtures.json`](web/public/fixtures.json) immediately.
To deliberately refresh metadata fixtures: `uv run python -m scripts.build_fixtures --fetch`,
then regenerate contracts and TypeScript types. This refresh changes source timestamps.

## Project context

Start with [the context guide](docs/context/README.md) for the product plan,
original build checklist and the owner’s four-screen HTML reference. The guide
also records differences that need resolution before implementing real rankings.

## Layout

| Folder | Responsibility |
| --- | --- |
| `harvest/` | Full Phase 3 collection, verified cache/audit, Phase 2 spike; normalization comes later |
| `api/` | Shared Pydantic contracts and mock FastAPI server |
| `web/` | Vite, React, TypeScript, Tailwind and lazy-loaded Plotly scaffold |
| `config/` | Illustrative mission profiles and draft relevance weights |
| `snapshots/sample/` | Checked metadata fixtures; real snapshots remain ignored |
| `sync/` | Reserved for Phase 12; exits clearly rather than pretending to sync |
| `infra/` | Environment readiness notes; deployment is a later phase |
| `docs/context/` | Supplied build plan, source inventory and scope decisions |
| `scripts/` | Contract exports and explicit fixture refresh |

## Scientific boundaries

Mission scenarios and weights are design assumptions, not NASA-approved mission
specifications, material certifications or fire-risk predictions. The rank route
returns no scores until reviewed normalized tests are available. A gap means no
matching evidence in this collection, not proof that no research exists. CSV row
counts include possible descriptions/units/blank rows and are not validated test counts.
All displayed scientific claims must trace to evidence; missing values stay null.

## Credits and handoff

NASA PSI is the source of the catalogue metadata. This independent project is not
NASA-endorsed. Software is MIT licensed; upstream data retains its own license.
See [references](REFERENCES.md), [AI disclosure](docs/AI_USAGE.md),
[Phase 1–2 handoff](docs/PHASE_1_2_HANDOFF.md) and the [supplied plan](docs/context/build-steps.md).
No public production deployment is included in these phases.

The complete-plan alignment adds canonical test/metric contracts, C/F/M/D ranking
weights, rover/custom scenarios and the exact eight requested context sources.
See [alignment status](docs/context/PLAN_ALIGNMENT.md) and
[session handoff](docs/context/SESSION_HANDOFF.md). Actual normalization and science
outputs remain later-phase work.
