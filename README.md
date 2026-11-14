# FireLens

Evidence-linked exploration of NASA microgravity combustion research.

**Status: Phases 1–2 foundation.** This repository contains a reproducible source
spike, shared data models, API contracts, offline fixtures and a React scaffold.
It is not yet the complete research dashboard. The preview uses five real NASA
catalogue records, zero normalized measurements and no live LLM. Null relevance
scores and an empty coverage map are intentional.

## Start locally

Prerequisites: Git, [uv](https://docs.astral.sh/uv/), Python 3.12 (uv can install it),
Node.js 22.12+ (use `.nvmrc`; Node 24 also works), npm, and optionally GNU Make.

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

## Check NASA access

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

## Layout

| Folder | Responsibility |
| --- | --- |
| `harvest/` | Source spike, row validation; later harvesting/normalization |
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
