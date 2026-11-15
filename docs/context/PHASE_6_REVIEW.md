# Phase 6 branch review — 14 November 2026

Reviewed branch: `feature/phase-6-test`, commit `59e740c`.
This checkpoint supersedes the Phase 3 branch/status assumptions in
`SESSION_HANDOFF.md`; that older file remains historical context.

## Current implementation

- Phase 4–5: YAML column maps, normalization, metadata/chunk/vector precomputation,
  Parquet snapshot writer and `harvest.pipeline` CLI.
- Phase 6: environment settings, Azure/OpenRouter/offline LLM wrapper, local/Blob
  snapshot loader, lazy 15-minute refresh, hourly optional catalogue cache,
  C/F/M/D ranking, filters, comparison, CSV/JSON exports and rate-limited SSE chat.
- Local ignored snapshot `20261114T164500Z`: 24 investigations, 1,858 test rows,
  2,632 chunks. Eleven tables are mapped per test; eleven remain study-level
  summaries/ranges. Stored embeddings are `local_hash_256`, not learned semantic
  embeddings. These are software artifacts, not independent scientific approval.
- Frontend remains the earlier contract preview; `App.tsx` passes an empty array
  to the coverage map and does not yet expose the full Phase 6 workflow.

## Verification

- `uv run ruff check .`: passed.
- `uv run ruff format --check .`: passed, 59 files.
- `uv run pytest -q`: 141 passed, including local real-snapshot API integration.
  One Starlette/httpx deprecation warning.
- Frontend lint/TypeScript checks passed; 10 tests passed; production build
  passed with a large Plotly bundle warning (approximately 1.09 MB uncompressed).
- No live paid model, Azure deployment or Docker runtime verification performed.

## Original review findings (see fixes below)

1. `api/llm.py:generate_grounded_answer` accepts live text if it contains any
   retrieved accession; this does not validate each claim, number or citation.
   `api/rag.py:stream_chat_events` labels answers supported whenever citations
   were retrieved, even if generation abstained. Strengthen these gates.
2. `api/snapshot.py:query_tests_by_sql_filter` excludes mock evidence but permits
   unreviewed rows; chunks are also retrieved without a review-status gate.
   Preserve review/uncertainty labels and prevent unsupported scientific claims.
3. `harvest/precompute.py` derives some reviewed flags from the presence of rows.
   A reviewed flag alone is not proof that a human completed a science audit.
4. Snapshot loading recomputes embeddings rather than reading the stored vector
   index; OpenRouter uses deterministic hash embeddings. Large Azure batches
   also fall back to hash embeddings, potentially differing from query vectors.
5. README, AGENTS, SESSION_HANDOFF, API description and build checklist still
   contain earlier-phase status. Structured request logging is not implemented.
6. Dockerfile includes only the sample snapshot; real-snapshot Docker operation
   still needs a mounted/downloaded snapshot and explicit runtime verification.
7. `api/main.py:_client_ip` trusts any `X-Forwarded-For` header. Direct callers
   can rotate that header to bypass the per-IP chat limit; trust only headers
   supplied by a configured reverse proxy.

The API implementation and tests are substantial; do not describe Phase 6 as
fully audited or the final dashboard as complete on this evidence alone.

## Follow-up: requested hardening implemented

- Live synthesis now uses structured excerpt selection. Every selected citation
  ID must belong to retrieved evidence, and its quote must equal the complete
  evidence text. Code renders DOI/locator tags; invented IDs, altered numbers,
  partial quotations and malformed output trigger the deterministic evidence
  fallback. This provides extractive answers rather than unrestricted prose;
  source review and question relevance still require scientific evaluation.
- Chat SQL permits reviewed measurement rows only, with an additional provenance
  guard before generation. Chunk retrieval excludes missing/unreviewed/fixture
  investigations and unreviewed summaries. Browse/export behavior is unchanged.
- Abstention now produces `insufficient_evidence` in both answer and done events,
  with no citations. Supported answers return only citations actually displayed.
- The rate limiter uses the connection peer; app code ignores forwarded headers.
  For a reverse proxy, configure Uvicorn `--forwarded-allow-ips` with only trusted
  proxy addresses; do not use `*` on an API reachable directly by clients.
  The limiter remains process-local; a multi-worker deployment needs a shared
  limiter or gateway enforcement.
- Regression tests cover invented citations/numbers, valid excerpt selection,
  unreviewed/simulated evidence, abstention and forwarding-header spoofing.
- Final verification: **152 Python tests passed**; Ruff lint/format and generated
  contract drift checks passed. No live model calls were used for verification.
  The owner authorized committing and pushing these fixes to `feature/phase-6-test`.
