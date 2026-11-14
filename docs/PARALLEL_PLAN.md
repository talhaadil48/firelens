# FireLens Parallel Execution Plan (Post Phase 3)

This plan assumes **`feature/phase-3-harvest`** is merged into `main` (PR #2) and all four teammates branch from `main` to work in parallel.

## Conflict-Free Rules ("Fixed Borders, Free Inside")

To move fast in parallel without merge conflicts or incompatible structures, **lock only the borders (handshakes) and give each teammate full freedom inside their own folder**:

| Track | Branch | Folders You Own (Edit Freely) | Do Not Edit Without Team Sync |
| --- | --- | --- | --- |
| **Data** | `feature/phase-4-5-data` | `harvest/`, `snapshots/` | `api/`, `web/`, `infra/` |
| **API & SI** | `feature/phase-6-api` | `api/` | `harvest/`, `web/`, `infra/` |
| **Web** | `feature/phase-7-web` | `web/` | `harvest/`, `api/`, `infra/` |
| **Cloud & Story** | `feature/phase-9-infra` | `infra/`, `sync/`, `.github/`, `REFERENCES.md` | `harvest/`, `api/`, `web/` |

1. **Zero-conflict folder ownership:** Only edit files in your own folder(s) plus your own unit tests in `tests/`.
2. **Never silently change a handshake file:** `api/models.py`, `harvest/validation.py`, `config/profiles.yaml`, `docs/contracts/openapi.json`, and `web/src/api.generated.ts` are shared borders. If a change is needed, agree in team chat first, update `api/models.py`, and immediately run `uv run python -m scripts.export_contracts` + `npm run generate:types --prefix web`.
3. **Run checks before every PR to `main`:** Run `uv run ruff check .`, `uv run ruff format --check .`, `uv run pytest`, `uv run python -m scripts.export_contracts --check`, and `npm run lint && npm test && npm run build` inside `web/`.

## Shared Locked Contracts (Do Not Break)

All four tracks integrate through these existing contracts—no track needs to wait for another to start:

| Contract | File | Owners / Consumers |
| --- | --- | --- |
| Row, Investigation, Rank, Chat & Snapshot models | `api/models.py` (`ExperimentalTest`, `Investigation`, `RankResponse`, `TextChunk`, `SnapshotPointer`) | All tracks |
| DataFrame schema validation | `harvest/validation.py` (`TestFrame`) | Data ↔ API |
| Column-map YAML schema | `harvest/maps_schema.py` (`ColumnMap`) + `harvest/maps/TEMPLATE.yaml` | Data |
| HTTP & SSE API spec | `docs/contracts/openapi.json` & `docs/contracts/sse.md` | API ↔ Web |
| TypeScript client types | `web/src/api.generated.ts` | Web |
| Profiles & C/F/M/D weights | `config/profiles.yaml` (`0.40 / 0.25 / 0.20 / 0.15`) | API ↔ Web |
| Snapshot directory layout | `snapshots/README.md` (`latest.json`, `tests.parquet`, `investigations.json`, `chunks.jsonl`, `vectors/`, `SNAPSHOT.md`) | Data ↔ API ↔ Cloud/Sync |

> **Contract change rule:** Only edit `api/models.py` if all affected tracks agree. Immediately run `uv run python -m scripts.export_contracts` and `npm run generate:types --prefix web` after any model change.

---

## Track Assignments (4 Parallel Branches)

### 1. Data Track — `feature/phase-4-5-data` (Phases 4 & 5)
**Goal:** Turn `raw/plan-aligned-20261114/` into a validated snapshot under `snapshots/<timestamp>/`.
1. **Column maps (`harvest/maps/PSI-<n>.yaml`):** Create and human-review maps (validating against `ColumnMap`) in priority order:
   - Priority 1: **CFI-G (`PSI-159`)**, **SPICE (`PSI-107`)**, **FLEX (`PSI-69`)**, **BASS-II (`PSI-25`)**, **BASS (`PSI-26`)**.
   - Priority 2: Remaining CSVs; mark unmappable range/summary tables `study_level_only: true`.
2. **Implement `harvest/pipeline.py`:**
   - `normalize`: apply maps, convert `mmHg`/`atm`/`bar` -> `kPa` and `%` -> `0–1`, parse dates/GMT, validate with `validate_tests`, write `tests.parquet`.
   - `precompute`: compute condition ranges per investigation, extract page-numbered PDF/DOCX text into `TextChunk` records (`chunks.jsonl`), generate `text-embedding-3-small` vectors (`vectors/`), and generate structured `InvestigationSummary` JSON (spot-checked by a human).
   - `snapshot`: write `SNAPSHOT.md` and `latest.json` (`SnapshotPointer`).

### 2. API & SI Track — `feature/phase-6-api` (Phase 6)
**Goal:** Replace `FIRELENS_MODE=mock` with live DuckDB/Parquet, C/F/M/D ranking, and grounded SSE `/chat`.
*Start immediately using `api/models.py`, synthetic `ExperimentalTest` fixtures, and unit tests—do not wait for Phase 4.*
1. `api/llm.py`: Azure OpenAI / OpenAI-compatible wrapper with mock mode.
2. `api/snapshot_loader.py`: load `latest.json` (`SnapshotPointer`) from Blob Storage or local `snapshots/`, fall back to baked-in copy, refresh pointer every 15 minutes.
3. `api/rank.py`: implement `R = 0.40 C + 0.25 F + 0.20 M + 0.15 D` in SQL/Python over `tests.parquet`, returning breakdown + explicit gap list.
4. `api/rag.py`: embed question -> top 8 `TextChunk` records -> structured SQL row filter -> streamed SSE `/chat` with mandatory `[PSI-XX, DOI, file p.N]` citations and per-IP rate limiting.
5. Update `/meta` with cached hourly PSI freshness check, `/compare` with field-grounded "same/different" summary, and `/export` for real CSV/JSON rows.

### 3. Web Track — `feature/phase-7-web` (Phase 7)
**Goal:** Build the full four-screen React + Plotly dashboard from `docs/context/reference/dashboard-ui-concept.html`.
*Start immediately in `VITE_DATA_MODE=mock`—do not wait for Phase 4 or Phase 6.*
1. Theme tokens (dark ground, flame-blue accent, Space Grotesk / Inter / JetBrains Mono) + header freshness badge + cold-start "waking up" state.
2. **Explorer:** Profile pills, condition readouts, ranked investigation cards with 4-part C/F/M/D score bars, Plotly Coverage Map with mission envelope box and gaps panel.
3. **Investigation Detail:** Structured summary with citations, tested conditions, table preview, documents/publications, related studies, copy-citation button.
4. **Compare:** 2–3 side-by-side columns, "same/different" paragraph, highlight-differences toggle.
5. **Ask FireLens & Export:** Streaming SSE chat UI with citation chips and evidence trace panel + CSV/JSON export modal.

### 4. Cloud, Sync & Story Track — `feature/phase-9-infra` (Phases 0, 9–10, 12–15)
**Goal:** Provision Azure + GoDaddy DNS, wire nightly sync, and prepare the Space Apps submission.
*Completely independent of Phases 4–7.*
1. Claim Space Apps Global Offers (Microsoft Azure + GoDaddy domain) and verify model availability in one Azure region (`infra/README.md`).
2. Provision `firelens-rg`, `firelensdata` (Blob `snapshots/`), `firelens-aoai`, `firelens-api` (Container App), `firelens-web` (Static Web App), `firelens-sync` (Container Apps Job), Managed Identities, and DNS (`www` + `api`).
3. Implement `sync/` nightly job and verify `make docker-api` / `make docker-sync`.
4. Maintain `REFERENCES.md`, run the 15 gold-question check against `/chat` once integrated, and assemble the 7-slide deck / 30s demo.

---

## Integration Sequence (Gates)
1. **Sync Point 1 (G1 — Snapshot Freeze):** Data Lead freezes `snapshots/<timestamp>/` and shares it (or uploads to `firelensdata`). API Lead points `api/` at the real snapshot and verifies all endpoints.
2. **Sync Point 2:** Web Lead switches `VITE_DATA_MODE=api` against `firelens-api` and runs end-to-end smoke tests across all 4 screens.
3. **Sync Point 3 (G2 — Live URL & Gold Check):** Cloud Lead deploys `firelens-api`, `firelens-web`, and `firelens-sync`, verifies DNS + TLS, and the team runs the 15 gold questions before final submission (G3).
