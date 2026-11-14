# FireLens — Phase 1 and Phase 2 handoff

Owner: Talha Adil (`talhaadil48`). Implementation date: 14 November 2026.
Scope: repository setup and feasibility/contracts only. No Phase 3–15 work is claimed.

## What was done

### Phase 1 — repository scaffold

| Step | Result |
| --- | --- |
| 1.1 | Created `harvest/`, `api/`, `web/`, `sync/`, `infra/`, `snapshots/sample/`, `docs/context/`, `scripts/` and `tests/`. Real raw data/snapshots are ignored. |
| 1.2 | Added README, AGENTS/CLAUDE instructions, original checklist, decisions, references, MIT software license, AI disclosure, ignore rules and secret-free environment examples. |
| 1.3 | Python 3.12 project, uv lockfile, api/harvest/dev dependency groups, Ruff and pytest. Vite/React/TypeScript/Tailwind/Plotly web project with lockfile, lint, component tests and generated API types. |
| 1.4 | Make targets for setup, spike/harvest, normalize, precompute, snapshot, API, web, lint/test/contracts, and both Docker builds. Later-phase commands explicitly exit as unimplemented rather than producing fake data. |
| 1.5 | GitHub Actions checks Python/web on pull requests and main pushes. Remote checks are attached to setup PR #1. |

### Phase 2 — spike and contracts

| Step | Result |
| --- | --- |
| 2.1 | Implemented and ran PSI catalogue → FLEX/CFI-G manifests → immediate signed-link CSV downloads. All THREE experimental tables succeeded; CFI-G has separate normal/inverse files. Timings, encoding, headers and SHA-256 hashes are in `SPIKE_RESULTS.json`. |
| 2.2 | Pydantic models for experiments, investigations, provenance, citations, profiles and API responses; Pandera validation for physical bounds, original source rows and compound test-ID uniqueness. Software validated; owner/science review is still required. |
| 2.3 | Exported OpenAPI, documented SSE events and a functioning offline contract server for every planned endpoint, plus `/profiles`. No production ranking, retrieval or LLM implementation is claimed. |
| 2.4 | Five fixtures use fetched NASA metadata: BASS, FLEX, CFI-G, Saffire-III and BASS-II. Generated example responses, SSE frames, shared TypeScript declarations and a basic searchable web preview. No invented measurements populate the map. |
| 2.5 | Added Earth, ISS, Moon-base, rover and spacesuit scenarios plus 0.40/0.25/0.20/0.15 weights. Labels distinguish design assumptions from NASA specifications. Unspecified rover values stay null. Dimension choices and scientific approval remain explicit review items. |

## Real data spike

- Catalogue search: 26 hits; 24 labelled Combustion Science.
- FLEX: 24,776 bytes; 274 CSV rows after header; cp1252 encoding.
- CFI-G normal flames: 22,166 bytes; 179 CSV rows after header; UTF-8.
- CFI-G inverse flames: 39,422 bytes; 1,015 CSV rows after header; UTF-8.
- These counts include any descriptions, units or blank rows. They are NOT verified test counts.
- Original CSVs/manifests are local under `raw/spike/`, deliberately not committed.
- Signed URLs are temporary credentials: never logged, stored or committed.
- Reproduce with `make spike`; this needs network access. Tests and fixtures run offline.

## How to run

```bash
uv sync --frozen
cd web && npm ci
cd ..
make api
# In another terminal:
make web
```

Use `http://127.0.0.1:8000/docs` for API docs and `http://127.0.0.1:5173` for the web preview.
The UI defaults to static fixtures. Set `VITE_DATA_MODE=api` and the base URL in
`web/.env.local` to use the local server. Copy from `web/.env.example`.

```bash
make lint
make test
make contracts
cd web && npm run generate:types
```

## Decisions needing owner/science review

1. The original checklist references a detailed plan and CLAUDE file that were not
   supplied. Read `docs/context/DECISIONS.md` for the provisional schema decisions.
2. Confirm ranking dimensions: oxygen / pressure / airflow / gravity in that order.
   No real score is computed before scientific validation.
3. Confirm illustrative mission envelopes. The rover's operating conditions were
   not provided. None of these config entries is an official NASA specification.
4. Approve the unified schema before implementing Phase 4 mapping rules.
5. Keep ambiguous units, ranges and lists for reviewed mappings. Do not turn them
   into fabricated scalar measurements.

## Environment limitations

- Git push authentication was verified for `talhaadil48` using existing Windows
  Git Credential Manager. Commits use the configured identity
  `talhaadil48 <talhaadil48@icloud.com>`; no credentials are stored in this repo.
- Linux Node.js 22 was downloaded and checksum-verified for local checks. Other
  machines should install Node using `.nvmrc`; no temporary tool path is required.
- Docker Desktop's WSL integration is unavailable here. Dockerfiles are supplied,
  but local image builds were not run. Azure CLI/account/region and domain offers
  are outside these phases and have not been verified or provisioned.
- No deployment, live model calls, purchases, domain changes or account enrollment.

## Verification and GitHub delivery

| Check | Observed result |
| --- | --- |
| PSI catalogue + experimental downloads | PASS: FLEX and both CFI-G CSVs saved; headers/hashes/timings recorded |
| Python lint and formatting | PASS |
| Python tests | PASS: 59 tests |
| OpenAPI/fixture drift | PASS; served OpenAPI includes the same SSE event definitions |
| TypeScript generation/type checking and web lint | PASS |
| Web tests | PASS: 8 tests |
| Production web build | PASS; Plotly is a separate lazy-loaded chunk |
| HTTP API smoke | PASS: metadata/list/rank/tests/compare/export and SSE chat |
| Credential/signature scan | PASS: no token or signed URL found in staged deliverables |
| npm dependency audit | 0 high/critical; 7 moderate findings in the development lint dependency chain (minimatch); not runtime dashboard code |
| Docker image builds | NOT RUN: Docker Desktop WSL integration unavailable |
| GitHub delivery | [Setup PR #1](https://github.com/talhaadil48/firelens/pull/1); GitHub Actions results attached to the PR |

The first dependency audit found outdated test tooling; it was replaced with
current Vite/Vitest/ESLint versions and checked again. The remaining moderate
transitive lint advisory requires a separately reviewed upstream update/override;
no forced incompatible downgrade was applied.

A server already occupied port 8000 in this environment, so the HTTP smoke check
used 18080 without stopping that existing service. Normal defaults remain 8000.
The test run reports an upstream Starlette/httpx deprecation warning, not a failure.

## Next work

Phase 3 harvesting, then reviewed mappings and normalization in Phase 4. API/web
teammates can already build against `docs/contracts/openapi.json`,
`snapshots/sample/responses.json`, `snapshots/sample/chat.sse` and
`web/public/fixtures.json`. Scientific UI numbers must wait for reviewed evidence.
