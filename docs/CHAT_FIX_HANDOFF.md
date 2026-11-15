# Active checkpoint: chat evidence/query fixes

Written 15 November 2026 at the owner's request to preserve progress before the
session limit. Start here when resuming; do not redo completed work.

## Current state and authorization

- Branch: `fix/chat-evidence-query-correctness`, based on `f190d73`.
- The correctness changes and this checkpoint are included in this branch's
  implementation commit. The checkpoint was originally written before commit;
  see the push-verification note below for the final validation scope.
- Owner requests: fix all failures from the ten-question chat audit; retain true
  missing-data explanations rather than fabricating measurements/charts.
- Multi-investigation frontend selection was already completed and pushed.
- Do not push main, deploy/provision cloud resources, expose secrets, or discard
  original raw files. No subagent delegation is authorized.
- Latest owner instruction: document changes and remaining work because little
  session budget remains. This checkpoint is not a claim of completion.

## Completed and pushed before this checkpoint

On `fix/chat-retrieval-and-cancellation`:

- `6e82e50`: lexical/semantic retrieval improvements and Stop cancellation.
- `a273da3`: selected-study summaries and literal flame-spread comparisons.
- `f190d73`: multi-study chat scope (up to ten IDs, removable chips, clear-all)
  and the original ten-question audit.

Earlier: investigation-page redesign (`ba3b439`) and full source-row preservation
with review-status removal (`8fccb23`). See PHASE_7_HANDOFF.md,
SOURCE_RECORDS_HANDOFF.md and CHAT_QUESTION_MATRIX.md for historical details.

## Environment and source data

- Repository: `D:/projects/hackathon/nasa-space-challenge/firelens`.
- Windows PowerShell; Python virtual environment is **WSL Ubuntu**, not Windows.
- Local frontend: http://localhost:5173, API mode targeting localhost:8001.
- Local backend: port 8001, running with `--reload`; current edits are active.
- Port 8000 belongs to another WSL/Docker service; do not stop it.
- Original environment files are preserved. Never print them or their keys.
- Snapshot: `snapshots/20261115-source-records-final/`, selected by latest.json.
- 24 investigations, **2,009 source records**, 22 CSVs, 2,632 text chunks.
- Source records include grouped/session/reference/note records; do not claim
  they are all independently validated experimental tests.
- Original nonblank cells/rows and hashes are retained under ignored
  `raw/plan-aligned-20261114`. Do not commit raw files or real snapshots.

Python commands from repository root:

```text
wsl -d Ubuntu --cd /mnt/d/projects/hackathon/nasa-space-challenge/firelens -- .venv/bin/python -m ruff check .
wsl -d Ubuntu --cd /mnt/d/projects/hackathon/nasa-space-challenge/firelens -- .venv/bin/python -m ruff format --check .
wsl -d Ubuntu --cd /mnt/d/projects/hackathon/nasa-space-challenge/firelens -- .venv/bin/python -m pytest -q --tb=short
wsl -d Ubuntu --cd /mnt/d/projects/hackathon/nasa-space-challenge/firelens -- .venv/bin/python -m scripts.export_contracts --check
```

Windows system Node is 20; use Node 22 for the web commands, from `web/`:

```text
npx --yes --package=node@22 node node_modules/vitest/vitest.mjs run
npx --yes --package=node@22 node node_modules/eslint/bin/eslint.js .
npx --yes --package=node@22 node node_modules/typescript/bin/tsc -b
npx --yes --package=node@22 node node_modules/vite/bin/vite.js build
```

## The audit and factual constraints

Exact ten original prompts/IDs: `tests/fixtures/chat_questions.json`.
Full local evidence under ignored `artifacts/question-matrix/`:

- `before-results.json`: original actual responses before these fixes.
- `results.json`: latest actual local answers, citations, progress and timings.
- `source-records.json`: actual source-row export used for independent checks.
- `chart-results.json`: rendered charts from replaying those exact SSE responses
  against real local row endpoints (avoids repeated model calls).
- `run_questions.py`, `check_charts.cjs`: reproducible local test scripts.

Correct study identities:

- PSI-69 FLEX; PSI-26 BASS; PSI-25 BASS-II.
- PSI-101 SAME-R; PSI-102 SAME; SAFFIRE-I/II/III are PSI-98/99/100.
- PSI-159 CFI-G; PSI-107 SPICE; PSI-10 Flame Design; FLEX-2 is PSI-68.

True data limits that must NOT be hidden:

- FLEX has methanol/heptane droplets, no PMMA/solid runs, and no airflow column.
- SAME-R/SAME have airflow but no exact oxygen-pressure pairs in imported tables.
- BASS-II has Flow restrictor/Fan display/Air display, not calibrated cm/s. Do
  not convert these settings into velocities without a calibration.
- CFI-G has 333 coordinate pairs. SPICE has airflow but no such pairs.
- The imported rows do not verify a lithium-ion thermal-runaway experiment in a
  Martian dust storm. This is not proof NASA has never studied the subject.

Original real failures: A2 ignored `oxygen concentrations above 30%` and cited a
21.23% oxygen row; A4 collapsed OR to an ethylene-only filter and substituted
airflow bars for coordinates; A1 gave irrelevant supported text; C1/C2 truncated
context; C3 failed to flag the conflicting Flame Design/PSI-159 identity.

## Current uncommitted implementation

### api/llm.py

Internal SqlRowFilter gains `fuels`, `fuel_or_phase`, and `exclusive` bound flags.
Parses variable-first oxygen wording and comparison symbols. Above/below are
strict; at least/at most inclusive. Multiple fuel comparisons retain their union.
Flame Design alias resolves PSI-10; incorrect FLEX-2 PSI-143 mapping becomes PSI-68.
This internal model is not a public shared API contract change.

### api/snapshot.py

SQL filter querying supports parameterized fuel unions, fuel OR phase, strict
comparisons, mock-provenance exclusion, and `all_matches=True` for exact totals.
Existing public query_tests behavior is unchanged. An initial broad replacement
accidentally referenced sql_filter inside query_tests; it was already corrected.

### api/answers.py — new

Code-owned measurement answers enforce deterministic filters before model calls.
They report exact match totals, explicitly label eight cited examples as a sample,
prefer rows containing requested quantities, explain unavailable fields and
calibration gaps, and avoid generic supported output when no rows match.
Availability citations reference actual snapshot metadata with a SHA-256 and
are labelled snapshot observations, not assertions of global NASA data absence.
Conflicting study-name/parenthesized-PSI pairs receive a cited correction without
silently changing scope. Document answers return complete source sentence windows
and distinguish hypotheses/objectives from observations. No invented narrative
or scientific result is generated to force a positive response.

### api/rag.py

Routes structured numeric questions before model generation, and science-context
questions through complete source windows. Existing summaries, comparative spread
answers, cancellation checkpoints and public SSE payloads remain. Structured
responses emit retrieval + answer progress events, then answer and done.

### Frontend

`ChatChart.tsx` no longer substitutes a different scalar when requested fields
are missing. Oxygen AND pressure requests require coordinate pairs. Handles
plural pressures/velocities and flow_cm_s. Regression tests cover both wrong-field
fallback directions. Multi-investigation selection remains intact.

### New tests

`tests/test_chat_question_matrix.py` has ten source-grounded expectations (skip
when the optional real snapshot is absent), parser/union tests, and a synthetic
DuckDB strict-boundary/OR test that runs without NASA files. Synthetic records
are explicitly test-only. Exact prompts are in `tests/fixtures/chat_questions.json`.

## Latest checks and what remains

1. New matrix/parser run initially had **14 passing tests**, before adding the
   synthetic SQL boundary case. Frontend: **33 passed**, lint, TypeScript and a
   fresh production build passed. A fresh full E2E run remains follow-up work.
2. Last full Python run: **172 passed, 3 failed** (175 total). All three failures
   were existing mock-contract tests receiving snapshot runtime leaked by the new
   module-scoped fixture. This was test isolation, not a product data failure.
3. **Fix applied and verified:** source_data fixture now yields and restores
   `configure_runtime(Settings(mode="mock", _env_file=None))` in a finally block.
   The subsequent full pytest run completed: **175 passed**, one existing
   Starlette/httpx deprecation warning. Ruff lint/format also pass. The three
   earlier mock-contract failures are resolved. No Python test run is pending.
4. Latest actual local run: all ten produce the expected truthful answer modes,
   without transport errors. A2 reports **257 matches**, eight cited examples
   satisfying strict bounds. A4 provides CFI-G coordinate examples and explains
   SPICE's missing fields. C3 corrects Flame Design to PSI-10.
5. Latest chart replay finished: **A2 scatter, A4 scatter**; all others have no
   chart because they ask about absent measurements or source context. A1/A3/
   B1/B2/D1 correctly remain insufficient_evidence with specific explanations.
6. Inspect C1/C2 explanation quality: returned source windows are grounded, but
   do not claim independent scientific validation. C2 available evidence states
   a hypothesis, not a universal proof of greater hazard at lower ventilation.
7. Add/run positive airflow-chart controls using measured datasets, e.g.
   `Compare airflow velocities in PSI-101` and an airflow question for PSI-107.
   Original B1/B2 must NOT be forced to draw nonexistent velocity measurements.
8. Rerun ten actual local questions and chart verification after final edits:

```text
wsl -d Ubuntu --cd /mnt/d/projects/hackathon/nasa-space-challenge/firelens -- .venv/bin/python artifacts/question-matrix/run_questions.py
node artifacts/question-matrix/check_charts.cjs
```

9. Run required Python/web checks above. Full Playwright needs **web/ as cwd**;
   root cwd causes misleading snapshot-related skips. Existing ignored
   `artifacts/readiness/playwright.config.cjs` uses Edge and ports 8018/4178.
   Start its offline QA API (`serve_api.py`) and an API-mode production preview;
   leave owner's 8001/5173 servers running. Previous full six-flow suite passed
   before these current correctness edits.
10. Update CHAT_QUESTION_MATRIX.md (currently ORIGINAL failures): retain history,
    append after-fix results and explain that missing-data/correction cases pass
    through truthful explanations, not charts. Update PHASE_7_HANDOFF.md.
11. Push target is only `fix/chat-evidence-query-correctness`.
    No main push or cloud deployment. Summarize implementation and limitations.

## Push verification

The owner subsequently requested committing and pushing the current fix branch.
Required Python lint/format/tests and contract drift checks, plus frontend
lint/tests/TypeScript/production build, were rerun before the push. The fresh
full six-flow browser suite and positive airflow controls remain follow-up
verification; no new browser or scientific-validation result is claimed here.

## Separate readiness issues

- Public URL supplied earlier:
  https://kind-smoke-0b5fbe80f.6.azurestaticapps.net/#/explorer
  Previously showed five fixtures/zero measurements due to Azure Blob snapshot
  validation failure. Owner clarified the CURRENT bug is LOCAL. Do not conflate
  these issues or autonomously change cloud resources.
- FLEX burning-rate unit was independently confirmed after the original audit:
  NASA/TP-2015-216046, printed pp.19–20 (PDF pp.25–26), Table IX matches CSV test
  20CAL08, value 0.52. **mm2/s is supported** despite the shortened CSV header.
  Source: https://ntrs.nasa.gov/api/citations/20150023456/downloads/20150023456.pdf
  Original retained at raw/science-checks/20150023456.pdf with .source.json.
  SHA256 b4f6ca983e2792c33a0b92220a791a818f426bb635b94f7fd33dc8c9c471e79d.
- Ranking remains a research-relevance heuristic, not a NASA safety score.
- No independently validated gold score, eligibility/submission verification or
  guaranteed hackathon win is claimed.
- Stop cancels delivery and future stages; an already-running synchronous
  upstream model call may still finish remotely.
- Existing advisories: Plotly bundle size and Starlette/httpx deprecation.
