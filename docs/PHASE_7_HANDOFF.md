# Phase 7 — FireLens research dashboard

Branch: `feature/phase-7-web`, created from `15e94c9` on `feature/phase-6-test`.
The owner requested a readable, professional interface with purposeful graphics,
then added evidence-grounded graphical answers in chat. No cloud deployment is
part of this change.

## What is implemented

| Checklist | Implementation |
| --- | --- |
| 7.1 Theme | Light and dark palettes, blue accents, amber uncertainty notices. Locally bundled Inter, Space Grotesk and JetBrains Mono from the supplied reference, with original licences. |
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
- Frontend: **25 tests passed**, ESLint/TypeScript passed, production build passed.
- Generated OpenAPI/fixtures drift check passed; generated TypeScript unchanged.
- Chromium: **5 production-build browser tests passed** against the real API:
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

## Appearance and coverage refinement — 15 November 2026

The owner requested both light and dark themes and a replacement for the original
"Tested conditions. Visible gaps." scatter plot.

- The header now has a labelled Light/Dark toggle. The choice is saved under
  `firelens-theme` in browser local storage, applied before initial paint, and
  synchronized between tabs. Dark remains the default. Storage failures do not
  prevent switching themes.
- Both themes cover navigation, cards, inputs, tables, comparison highlights,
  dialogs, citations, warnings and Plotly scatter/bar labels and grids.
- The coverage panel is now "Where has NASA tested?" with exact-condition
  bubbles. Only identical oxygen/pressure coordinates are combined; all source
  rows and source-study links remain available. Bubble size represents test
  count, never fire severity. There is no binning, interpolation, jitter or
  inferred measurement.
- Outcome filters show original reported categories and counts. The default
  0–120 kPa cabin display preset makes lower-pressure conditions readable, with
  an explicit count/link for higher-pressure tests. Full range restores the
  overview. The 120 kPa display choice is not a NASA operating limit.
- Counts describe the selected pressure preset rather than claiming to track
  manual Plotly zoom/pan. The accessible table includes all outcome-filtered
  source rows, including points outside the initial pressure preset.
- A clicked bubble exposes the exact condition, represented test count and links
  to every contributing investigation, avoiding an arbitrary navigation choice
  when studies share conditions.
- New tests cover exact grouping, preservation of high-pressure rows, exclusion
  of unreviewed/simulated/mock/missing-coordinate data, and persisted theme choice.
- Verified: 25 frontend tests passed; lint/TypeScript and production build passed.
  Five browser flows passed against the real snapshot, including both themes,
  reload persistence, full-range switching, outcome filtering and mobile layout.
  Light/dark screenshots are in ignored `artifacts/phase7/coverage-*.png`.

Browser QA can now run without stopping the owner's servers. Override
`FIRELENS_E2E_API_PORT` and `FIRELENS_E2E_WEB_PORT` (defaults 8017 / 4177).
For this run QA used 8018 / 4178; the owner's API on 8017 and frontend on 5173
were kept running. When testing a production build, its `VITE_API_BASE_URL`
must match the selected QA API port.

The additional targeted light-mode browser run also passed: bubble selection
opened contributing study links, the export dialog used the light palette,
source-backed chat pressure bars rendered correctly, and the 393-pixel mobile
layout had no horizontal overflow. No application backend or source data changed.

Publications refinement: the investigation publication list now scrolls inside a
360-pixel maximum viewport (also bounded to half the screen height), with the
section heading retained above it. The region is keyboard-focusable and uses
theme-aware scrollbar colours. Verified on FLEX: 6,419 pixels of content stayed
inside a 360-pixel list and Page Down scrolled it successfully.

Investigation layout refinement: all seven content sections now use named,
keyboard-focusable scroll regions with height limits. Overview content is capped
at 440 px, findings/documents/publications at 360 px, source metadata and test
rows at 340 px, and related studies at 260 px; viewport-relative mobile limits
reduce those sizes on shorter screens. Short content retains its natural height.
Headings remain outside the scrolled content. The test table scrolls on both axes
inside one region and retains a sticky, theme-aware header. No source text,
publication or test data was discarded. Browser verification against FLEX passed
for all seven height bounds, Page Down scrolling, retained headings, light-mode
table headers and a 393 px mobile layout without horizontal page overflow.

## Investigation page redesign — 15 November 2026

The owner requested a complete investigation-page layout replacement after a
screenshot showed unused space beside the findings. The page now has a compact
study header, normalized-test/condition readouts and keyboard-accessible Overview,
Findings, Measurements and Sources & publications tabs. Each tab uses the content
width; the former independently scrolling main/sidebar stacks are gone. Overview
facts use a responsive grid. Measurements and lengthy publications retain bounded,
labelled scroll regions. Copy citation, export and compare remain available in the
header. Reviewed-only findings, citation excerpts, provenance and missing-value
labels are retained without backend or contract changes.

Verified: 25 frontend tests (including section switching and keyboard navigation),
ESLint, TypeScript and production build. Browser checks against the local snapshot
covered all tabs, keyboard switching and desktop/393px layouts without horizontal
page overflow. Light/dark desktop and mobile screenshots are retained under ignored
`artifacts/phase7/investigation-redesign-*.png`. The existing Plotly bundle-size
advisory remains. No deployment or cloud provisioning was performed.
