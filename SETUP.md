# FireLens Setup Guide (`feature/phase-3-harvest`)

This guide walks through setting up, running, and verifying the **`feature/phase-3-harvest`** branch of **FireLens**.

> **Current scope:** This branch implements **Phases 1–3** (repo scaffold, shared Pydantic/Pandera contracts, offline mock API & web preview, and the full Phase 3 NASA PSI harvester). Normalization (Phase 4), reviewed summaries/embeddings (Phase 5), live ranking/RAG (Phase 6), the full four-screen UI (Phase 7), and cloud deployment are not yet implemented. No API keys or cloud accounts are required.

---

## 1. Prerequisites

| Tool | Required version | Notes |
| --- | --- | --- |
| **Git** | Any recent version | For cloning and switching branches |
| **uv** | Latest | Manages Python 3.12 (`.python-version`) and locked dependencies (`uv.lock`) |
| **Python** | `>=3.12,<3.14` | `uv` can install Python 3.12 automatically |
| **Node.js** | `>=22.13.0 <23` or `>=24.0.0` | See `.nvmrc` (`22`) and `web/package.json` |
| **npm** | Bundled with Node | Used for `web/` |
| **GNU Make** | Optional | Convenience wrapper around `uv` and `npm` commands (`Makefile`) |

### Windows + WSL note
If you use both **WSL (Linux)** and **Windows PowerShell** on the same repository folder, do **not** share one `.venv` between them. Set a separate `UV_PROJECT_ENVIRONMENT` on Windows (for example, `$env:UV_PROJECT_ENVIRONMENT=".venv-win"`) so Windows and Linux virtual environments do not overwrite each other.

---

## 2. Clone and Check Out the Branch

```bash
git clone https://github.com/talhaadil48/firelens.git
cd firelens
git fetch origin
git checkout feature/phase-3-harvest
```

---

## 3. Install Dependencies

### With `make`
```bash
make setup
```

### Without `make`
```bash
uv sync --frozen
cd web
npm ci
cd ..
```

---

## 4. Environment Files (Optional)

Everything works out of the box with defaults, and **no secrets or API keys are needed** for Phase 1–3:

- Root `.env.example` defaults to `FIRELENS_MODE=mock`, `FIRELENS_CORS_ORIGINS=["http://localhost:5173"]`, and `PSI_BASE_URL=https://psi.nasa.gov`. Azure OpenAI / Storage variables are for later phases only.
- To connect the web frontend to the local FastAPI server instead of static `web/public/fixtures.json`:
  ```bash
  cp web/.env.example web/.env.local
  ```
  Then edit `web/.env.local` to set:
  ```env
  VITE_DATA_MODE=api
  VITE_API_BASE_URL=http://127.0.0.1:8000
  ```

---

## 5. Run the Phase 3 NASA PSI Harvest

The Phase 3 collector paginates the public NASA PSI catalogue, filters `Research Area = Combustion Science`, downloads all manifests, experimental CSVs, Reports/Science Documents under 20 MB, and captures 8 NASA context sources. Bulk `Raw Data` (TB-scale video/images) is skipped.

```bash
uv run python -m harvest.run
# or: make harvest
```

### Useful flags
- `--workers 4` — set download concurrency (default is 3).
- `--refresh` — refresh catalogue, manifests, and context pages instead of reusing cached responses.
- `--offline` — forbid network requests and replay from the verified on-disk cache under `raw/_cache/` (do not combine with `--refresh`).
- `--run-id <name>` — write to `raw/<name>/` (resumes a partial run if that folder was incomplete; completed run folders are immutable).

### Output & expected status
- Downloaded files are stored under git-ignored `raw/<run-id>/`:
  - `catalogue/` (`page-*.json`, `combustion.json`)
  - `PSI-<number>/` (`manifest.json`, `inventory.json`, `*.csv`, `documents/`, `harvest.json`)
  - `context/` (HTML, PDF, extracted `.txt`, `.source.json`)
  - `report.json` and `HARVEST_LOG.md`
- **Expected partial exit:** Two legacy `PSI-26` report entries (`PSI-26_Reports_SPICE_FinalReport.pdf` and `PSI-26_Reports_BASS_FinalReport.pdf`) return HTTP 404 upstream, and the official challenge resource page may be unreachable depending on network access. Because of the two missing PDFs, `harvest.run` logs the failures honestly, marks the run `partial`, and exits nonzero.

### Verify file integrity
Audit any harvested run folder's SHA-256 checksums, file sizes, and context URLs:
```bash
uv run python -m harvest.verify raw/<run-id>
```
`integrity_ok` reports whether all retained files match their recorded hashes/sizes; `harvest_complete` reports whether all upstream requests succeeded (false if any source returned 404).

### Quick Phase 2 spike (optional)
To test only the PSI catalogue + `PSI-69` (FLEX) and `PSI-159` (CFI-G) CSV downloads:
```bash
uv run python -m harvest.spike
# or: make spike
```

---

## 6. Run the Local Contract API & Web Preview

In **terminal 1** (FastAPI contract server at `http://127.0.0.1:8000/docs`):
```bash
uv run uvicorn api.main:app --reload --host 127.0.0.1 --port 8000
# or: make api
```

In **terminal 2** (Vite React preview at `http://127.0.0.1:5173`):
```bash
cd web
npm run dev -- --host 127.0.0.1
# or from repo root: make web
```

> **Note:** The API and web UI currently serve Phase 2 mock fixtures (`FIRELENS_MODE=mock`). Relevance scores are `null` and the coverage map has no normalized test points until Phases 4–6 are implemented.

---

## 7. Run All Checks (Lint, Tests, Contracts, Build)

### Python checks
```bash
uv run ruff check .
uv run ruff format --check .
uv run pytest
uv run python -m scripts.export_contracts --check
```

### Web checks
```bash
cd web
npm run lint
npm test
npm run build
cd ..
```

Or with `make`:
```bash
make lint
make test
```

---

## 8. Regenerating Contracts, Fixtures, and TypeScript Types

If you change `api/models.py` or `api/main.py`:
1. Regenerate OpenAPI & sample fixtures:
   ```bash
   uv run python -m scripts.export_contracts
   ```
2. Regenerate TypeScript types for the web client:
   ```bash
   cd web && npm run generate:types && cd ..
   ```
3. To refresh metadata fixtures from retained cache (offline) or live NASA manifests:
   ```bash
   uv run python -m scripts.build_fixtures --from-cache raw/fixtures
   # or with network: uv run python -m scripts.build_fixtures --fetch
   ```

---

## 9. Key Documentation

- [README.md](README.md) — project overview and layout
- [AGENTS.md](AGENTS.md) — repository rules and scientific integrity boundaries
- [docs/context/README.md](docs/context/README.md) — context reading order
- [docs/context/flame-in-freefall-plan.md](docs/context/flame-in-freefall-plan.md) — complete product plan
- [docs/context/PLAN_ALIGNMENT.md](docs/context/PLAN_ALIGNMENT.md) — alignment status and remaining later-phase work
- [docs/context/SESSION_HANDOFF.md](docs/context/SESSION_HANDOFF.md) — latest branch checkpoint
- [docs/PHASE_3_HANDOFF.md](docs/PHASE_3_HANDOFF.md) — detailed Phase 3 harvester and audit reference
- [docs/harvest/HARVEST_LOG.md](docs/harvest/HARVEST_LOG.md) — latest executed harvest inventory
