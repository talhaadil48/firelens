# Phase 7 — FireLens research dashboard

Branch: `feature/phase-7-web`, created from `15e94c9` on `feature/phase-6-test`.
The owner requested a readable, professional interface with purposeful graphics,
then added evidence-grounded graphical answers in chat. No cloud deployment is
part of this change.

## What is implemented

| Checklist | Implementation |
| --- | --- |
| 7.1 Theme | Dark navy, blue accents, amber uncertainty notices. Locally bundled Inter, Space Grotesk and JetBrains Mono from the supplied reference, with original licences. |
| 7.2 Shell | Hash routes, active navigation, snapshot/date badge from `/meta`, source credit, data provenance screen. |
| 7.3 Explorer | Mission pills, custom O2/pressure/flow/gravity inputs, safety goal, C/F/M/D bars, ranked cards, filters, gaps and assumptions. Plotly oxygen-versus-pressure coverage, outcomes, scenario envelope/target, click-through study links. All API pages loaded; missing/unreviewed points excluded. Six cards initially, with Show more. |
| 7.4 Detail | Source metadata, reviewed summaries/findings, source snippets, condition ranges, hardware/sensors, first ten normalized rows, documents, publications, DOI/copy citation, related studies. |
| 7.5 Compare | Two or three distinct investigations, shareable URLs, difference highlighting, field-grounded summary and source links. |
| 7.6 Ask | SSE progress, cancellation, suggested questions, optional study scope, inline citation buttons, source excerpt/row panel and retrieval trace. Explicit error/abstention states. |
| Chat graphics | Automatically shows a scatter or bar chart when at least two comparable cited measurements exist. Matches citation IDs, accession, source file/row/version/hash, evidence type and review status before plotting. Source-table toggle; no LLM-generated numbers or executable chart code. |
| 7.7 Export | Native accessible dialog, CSV/JSON, entire snapshot/current study/filtered studies, metrics and metadata options, reviewed-only option, preview, download. Provenance, DOI, review labels and units always retained. |
| 7.8 Startup | Immediate shell and visible connection/loading stages, retry on failure; chart loading independent of the rest of the workspace. |
| 7.9 Accessibility | Labelled controls, keyboard focus, skip link, native dialog with Escape/focus behavior, mobile layouts, accessible chart tables, outcome symbols as well as colours, reduced-motion support. |
| 7.10 Modes | `VITE_DATA_MODE=mock` or `api`; shared typed client. Mock fixtures remain metadata only and cannot invent plots/scores. |
| 7.11 Stretch | Read-only active snapshot and review queue. Remote Sync now and historical snapshots remain unavailable because Phase 6 has no endpoints for them. |

The API currently labels the `mode` contract as mock even for snapshots. The UI
uses its explicit connection mode and fixture/test metadata to avoid presenting
real snapshot data as invented demo measurements. It does not silently change
shared backend contracts in this phase.

## Run on Windows or Linux

At the repository root:

```text
uv sync --frozen
```

If you do not have the ignored raw files/snapshot yet, collect and generate them:

```text
uv run python -m harvest.run
uv run python -m harvest.pipeline all
```

A partial harvest reports missing source files explicitly. Review its log before
using the resulting data; do not treat a review flag as independent validation.
Existing raw files/snapshots do not need downloading again.

In the root `.env` use `FIRELENS_MODE=snapshot`. Use `LLM_PROVIDER=offline` for
verification without paid model calls. Start the API from the repository root:

```text
uv run uvicorn api.main:app --reload
```

In another terminal, inside `web/`:

```text
npm ci
```

Copy `web/.env.example` to `web/.env.local` (PowerShell:
`Copy-Item .env.example .env.local` while inside `web/`). Set:

```text
VITE_DATA_MODE=api
VITE_API_BASE_URL=http://localhost:8000
```

Then `npm run dev` and open `http://localhost:5173`. Restart Vite after changing
its environment. Vite does not read the repository-root `.env` automatically.
Only public `VITE_*` settings belong in the web environment; keys stay backend-only.
Use `VITE_DATA_MODE=mock` for the intentionally empty offline metadata preview.

## Verification commands

From `web/`:

```text
npm run lint
npm test
npm run build
npx playwright install chromium
npm run test:e2e
```

Browser tests start their own API (port 8017) and Vite (4177), explicitly offline,
with cloud snapshot fetching disabled. They use the real ignored local snapshot;
if `snapshots/latest.json` is absent they skip rather than invent science data.
Those ports must be free. Browser artifacts go to ignored `artifacts/phase7/`.
No live LLM key or cloud account is needed. Python checks remain:

```text
uv run ruff check .
uv run ruff format --check .
uv run pytest
uv run python -m scripts.export_contracts --check
```

## Verification results

Verified locally against snapshot `20261114T164500Z`:

- Python: **152 tests passed**, Ruff lint/format passed.
- Frontend: **20 tests passed**, ESLint/TypeScript passed, production build passed.
- Generated OpenAPI/fixtures drift check passed; generated TypeScript unchanged.
- Chromium: **4 production-build browser tests passed** against the real API:
  full explore/detail/compare/ask/export flow; mobile layout/accessible data;
  three-study comparison and pressure bar chart; custom scenario, filtered
  274-row FLEX export, Escape and focus restoration.
- Dedicated graphical-evidence tests reject unreviewed, uncited, mismatched-row,
  mismatched-version and mismatched-hash data. Missing values are not inferred.
- Screenshots were visually inspected for desktop/mobile; local images and a
  verified CSV are under ignored `artifacts/phase7/`.
- No paid model calls, deployment or source downloads were needed for these checks.

The Plotly shared chunk is lazy-loaded (about 1.09 MB raw / 361 KB gzip); Vite
reports a bundle-size advisory. One existing Starlette/httpx deprecation warning
remains in the Python suite. In this Linux environment, missing Chromium system
libraries were extracted under `/tmp/firelens-browser-libs/` for QA; system
packages were not changed. On a fresh Linux machine, use Playwright's documented
browser dependencies setup if needed.

For production browser QA, build with `VITE_DATA_MODE=api` and
`VITE_API_BASE_URL=http://127.0.0.1:8017`, then run `npm run test:e2e` with
`FIRELENS_E2E_PREVIEW=1`. This serves `dist/` rather than Vite's development server.
Do not deploy that test-only API URL; configure the real public API URL when
building for deployment.

## Limits and next phase

- Charts compare observed measurements; no regression, flammability boundary,
  certified fire risk or partial-gravity prediction is inferred.
- A source-backed answer can still be irrelevant to a question. Scientific review
  and the Phase 8 gold-question evaluation remain necessary.
- Citation links open the published source; row/page locators and excerpts are
  displayed alongside them. A document link may resolve to its dataset page.
- The API provides whole answer events, not token-by-token model streaming.
- The browser loads the current table for complete coverage; a much larger future
  dataset should add server-side chart aggregation and export streaming.
- Data status is read-only. Deployment, nightly sync and the judging package are
  later milestones.
