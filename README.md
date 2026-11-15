# FireLens

Evidence-linked exploration of NASA microgravity combustion research.

**Status: Phase 7 dashboard on `feature/phase-7-web`.** Explorer, reviewed
coverage charts, investigation detail, comparison, source-linked chat (including
charts of cited measurements) and CSV/JSON exports connect to the Phase 6 API.
Light/dark appearance is available from the header. The coverage view groups
identical tested conditions and offers outcome filters and explicit pressure ranges.
Mock mode stays an explicitly empty metadata preview. A local ignored snapshot
contains 24 investigations and 1,858 normalized tests; it must be generated on a
fresh checkout. See [Phase 7 setup and verification](docs/PHASE_7_HANDOFF.md).

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
make api     # http://127.0.0.1:8000/docs — mode configured in root .env
make web     # http://127.0.0.1:5173 — offline fixtures by default
```

Without Make: `uv run uvicorn api.main:app --reload` and `cd web && npm run dev`.
To test the UI against the API, copy `web/.env.example` to `web/.env.local`, set
`VITE_DATA_MODE=api`, and restart Vite. For real data, set root `.env` to
`FIRELENS_MODE=snapshot` and generate `snapshots/latest.json` using
`uv run python -m harvest.pipeline all` after harvesting. Set `LLM_PROVIDER=offline`
to verify without paid model calls. No cloud account is required.

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
NASA report URLs returned 404, so it is honestly labelled partial. Normalization
and snapshot generation are separate from collection; see the Phase 7 handoff.
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
| `harvest/` | Collection, reviewed column maps, normalization and snapshot precomputation |
| `api/` | Typed API, DuckDB ranking/filtering, reviewed-evidence RAG and exports |
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
only scores investigations with eligible reviewed measurements and sufficient
conditions; other scores stay null. A gap means no
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
[session handoff](docs/context/SESSION_HANDOFF.md) for history. Current normalization,
API and dashboard behavior are documented in the [Phase 7 handoff](docs/PHASE_7_HANDOFF.md).
Scientific evaluation, deployment and scheduled sync remain later-phase work.
