# FireLens

Evidence-linked exploration of NASA microgravity combustion research.

**Status: data and API in place; web screens, chat and deployment in progress.**
The committed snapshot (`snapshots/latest.json`) holds 24 PSI Combustion Science
investigations, normalized test rows from five investigations (CFI-G, SPICE, FLEX,
BASS-II, BASS) and a text corpus of catalogue fields, report pages and context pages.
Column maps are drafts until a person reviews them, so rows are marked unreviewed. No
embeddings or AI summaries yet; `/chat` is still the offline contract stub. The web app
is the Phase 2 scaffold. See `snapshots/<id>/SNAPSHOT.md` for exact counts.

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

## Start with Docker (no local Python/uv/Node needed)

Only Docker is required. The dev image (`docker/dev.Dockerfile`) has Python 3.12,
uv, Node 22, make and git; the repo is bind-mounted, so edits reload live.

```bash
docker compose up --build        # API http://localhost:8000/docs, web http://localhost:5173
docker compose run --rm dev make test          # or: make lint, make contracts, make spike
docker compose run --rm dev bash               # shell with every tool installed
docker compose down                            # stop (add -v to drop cached deps)
```

By default the API serves the committed snapshot (unreviewed rows included, with a
warning) and the web calls the API. `FIRELENS_MODE=mock VITE_DATA_MODE=mock docker compose up`
brings back the Phase 2 fixtures. Model credentials, when you have them, go in `.env`
(see `infra/README.md`); the API container reads it.
In VS Code, **Dev Containers: Reopen in Container** uses `.devcontainer/` to open the
whole repo inside the same image; then run `make api` and `make web` in its terminal.

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
| `infra/` | Azure provisioning script (`provision.sh`) and runbook; a person runs it |
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
