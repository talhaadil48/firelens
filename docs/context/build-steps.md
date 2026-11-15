# FireLens: build and deploy steps, in order

Every step needed to develop, deploy and submit FireLens, in dependency order. Read with `CLAUDE.md` and `flame-in-freefall-plan.md`.

**Who:**
- **Person**: needs a human (logins, portals, payments, approvals, judgement calls).
- **Claude Code**: can be done in the repo or with CLI tools once logged in.
- **Both**: Claude Code drafts, a person checks.

**Gates (PKT, hard):**
- **G1**: snapshot v1 frozen, Sun 15 Nov 03:00
- **G2**: live on Azure with the custom domain, Sun 14:00
- **G3**: project submitted, Sun 22:30 (deadline 23:59)

**Parallel tracks after Phase 2:** Data (Phases 3–5), API (6), Web (7) and Cloud (9) run side by side. The API and web build against the contract and mock JSON from Phase 2 until the real snapshot lands.

---

## Phase 0: Accounts and admin (Person, start now)

- [ ] **0.1** Every teammate registered for the 2026 challenge, same local event, listed on the team page. *Done when:* all names show on the Members tab. (A mismatch blocks global judging.)
- [ ] **0.2** Claim the Global Offers (logged in at spaceappschallenge.org → 2026 Global Offers): GoDaddy (domain + hosting) and Microsoft (Azure). *Done when:* the Azure subscription is active and the GoDaddy offer is redeemed.
- [ ] **0.3** In Azure, pick one region that has the chat model and `text-embedding-3-small` available. *Done when:* the region is written in `infra/README.md`.
- [ ] **0.4** Register the domain on GoDaddy (e.g. `firelens.space` or whatever the offer allows). *Done when:* the domain shows in the GoDaddy DNS panel.
- [ ] **0.5** Create the GitHub repo `firelens`. Add teammates and enable GitHub Container Registry (GHCR) packages. *Done when:* everyone can push.
- [ ] **0.6** Install locally: Python 3.12, Node 20+, Docker, Azure CLI (`az login`), GitHub CLI (`gh auth login`).

## Phase 1: Repo scaffold (Claude Code)

- [ ] **1.1** Folders: `harvest/`, `api/`, `web/`, `sync/`, `infra/`, `snapshots/` (git-ignored except a sample), `docs/context/`, `scripts/`.
- [ ] **1.2** Add `CLAUDE.md`, the context files, `README.md` (stub), `REFERENCES.md` (start listing sources now), `LICENSE`, `.gitignore`, `.env.example` (no real secrets).
- [ ] **1.3** Python: `pyproject.toml` with harvest/api dependency groups; ruff + pytest. Web: Vite + React + TypeScript + Tailwind + Plotly.
- [ ] **1.4** Add a `Makefile` (or `justfile`) with targets: `harvest`, `normalize`, `precompute`, `snapshot`, `api`, `web`, `test`, `docker-api`, `docker-sync`.
- [ ] **1.5** CI on pull request: lint + tests for Python and web. *Done when:* the first PR is green.

## Phase 2: Spike and contracts (do before any large build)

- [ ] **2.1** *(Claude Code)* Spike script: call the PSI catalogue, fetch the FLEX (PSI-69) and CFI-G (PSI-159) manifests, then download both experimental CSVs via the signed-link flow. Log timings. *Done when:* both CSVs are saved and their headers printed.
- [ ] **2.2** *(Both)* Define the unified **test schema** and **investigation record** as Pydantic models plus Pandera checks (fields in the plan's Data pipeline section). *Done when:* reviewed and merged.
- [ ] **2.3** *(Claude Code)* Define the **API contract** as an OpenAPI spec or typed models: `/meta`, `/investigations`, `/investigations/{id}`, `/rank`, `/tests`, `/compare`, `/export`, `/chat` (streamed with Server-Sent Events, SSE).
- [ ] **2.4** *(Claude Code)* Write **mock JSON** fixtures matching that contract, using real facts from the context (BASS, FLEX, CFI-G, SAFFIRE-III, BASS-II). *Done when:* the web team can build against them.
- [ ] **2.5** *(Both)* Fix the **mission profiles** in config: Earth, ISS, Moon base (≥30% O2, ≤70 kPa), rover, spacesuit (100%, 30 kPa); plus the ranking weights (0.40 / 0.25 / 0.20 / 0.15).

## Phase 3: Harvest (Data track, Claude Code)

- [ ] **3.1** Catalogue: fetch, keep Research Area = Combustion Science, save the raw JSON.
- [ ] **3.2** Manifests: for each accession, fetch the detail record. Use concurrency 3–4, retries with backoff, and an on-disk cache. Save DOI, version, licence, hardware and the file list.
- [ ] **3.3** Experimental tables: request each download link and fetch the signed URL immediately. Save the CSVs as they are under `raw/PSI-<n>/`.
- [ ] **3.4** Documents: download only Reports and Science Documents under 20 MB. Skip Raw Data.
- [ ] **3.5** Context pages: scrape the challenge resource pages (Apollo 1, Apollo 13, Mir, Spinoffs, the NASA combustion page, the Researcher's Guide) to text with their URLs.
- [ ] **3.6** Write a dated raw folder plus `HARVEST_LOG.md` (counts, failures, timings). *Done when:* about 22 investigations and all their experimental CSVs are on disk.

## Phase 4: Normalize (Data track)

- [ ] **4.1** *(Claude Code)* LLM column-mapper: for each CSV, propose a `maps/PSI-<n>.yaml` mapping source columns to the unified schema, including units and split rules.
- [ ] **4.2** *(Person)* Review and correct each YAML. Priority order: CFI-G, SPICE, FLEX, BASS-II, BASS; then the rest.
- [ ] **4.3** *(Claude Code)* Apply the maps in code. Handle:
    - unit conversions: mmHg, atm and bar to kPa; percent to fraction;
    - multi-value cells ("21; 26.5; 40");
    - ranges ("1.5 - 5");
    - day-of-year (GMT) dates;
    - outcome labels.
- [ ] **4.4** *(Claude Code)* Pandera validation: O2 between 0 and 1, pressure above 0, no duplicate test IDs, provenance on every row. Unit tests for each conversion.
- [ ] **4.5** *(Claude Code)* Tables that can't be mapped cleanly (e.g. SAFFIRE-III's 2 rows, FLEX-2's ranges) stay as investigation-level metadata. *Done when:* `tests.parquet` and `investigations.json` pass validation.

## Phase 5: SI precompute and snapshot (Data track)

- [ ] **5.1** *(Claude Code)* Compute each investigation's condition ranges, row counts, fire-safety tag (prevention / detection / suppression) and fuel phase.
- [ ] **5.2** *(Claude Code)* Extract text from the PDFs and DOCX files with page numbers. Chunk into 500–800 tokens with metadata: accession, DOI, file, page, version, URL.
- [ ] **5.3** *(Claude Code)* Embed the chunks, catalogue text fields and context pages with `text-embedding-3-small`; store them in LanceDB.
- [ ] **5.4** *(Claude Code)* Generate structured summaries (JSON) from the catalogue fields, computed ranges and report text. Every key finding carries a source.
- [ ] **5.5** *(Person)* Spot-check all summaries and fix anything wrong.
- [ ] **5.6** *(Claude Code)* Write `snapshots/<timestamp>/` (Parquet, JSON, chunks, vectors, `SNAPSHOT.md`) and `latest.json`.
- [ ] **5.7 = G1** Freeze snapshot v1. Also copy it into the API image as a fallback.

## Phase 6: API (API track, Claude Code; starts on mocks after Phase 2)

- [ ] **6.1** Settings from environment variables. `llm.py` wrapper for Azure OpenAI, with a mock mode for offline development.
- [ ] **6.2** Snapshot loader: read `latest.json` from Blob Storage, fall back to the baked-in copy, re-check the pointer every 15 minutes and swap the data in memory.
- [ ] **6.3** `/meta`: snapshot id and date, counts, and a cached hourly PSI catalogue check (new releases since the snapshot).
- [ ] **6.4** `/investigations` and `/investigations/{id}`: records, summaries, DOIs, file links, related investigations.
- [ ] **6.5** `/rank?profile=` (or custom O2 / pressure / flow): conditions proximity in SQL, the weighted formula, score breakdown, gaps list.
- [ ] **6.6** `/tests`: filtered rows for the coverage map. `/compare?ids=`: side-by-side fields plus a "same and different" paragraph written only from those fields.
- [ ] **6.7** `/export`: CSV or JSON with a citation header and source file/row columns. Missing values stay empty.
- [ ] **6.8** `/chat` (streamed): rate limit → embed the question → top 8 chunks → model asks for rows through a structured filter → API runs SQL → answer with required citations. Say so when nothing is found; refuse out-of-scope topics. Stream progress events for the trace panel.
- [ ] **6.9** CORS limited to the web domain; per-IP rate limit on `/chat`; structured logs.
- [ ] **6.10** pytest for ranking, conversions, export and citation format. Dockerfile for `firelens-api`. *Done when:* `docker run` serves every endpoint against the snapshot.

## Phase 7: Web (Web track, Claude Code; starts on mocks after Phase 2)

- [ ] **7.1** Theme tokens from the UI design: dark ground, flame-blue accent, amber for warnings; Space Grotesk, Inter, JetBrains Mono.
- [ ] **7.2** App shell: header navigation, freshness badge from `/meta`, footer with data credit, routing.
- [ ] **7.3** **Explorer**: profile pills, condition readouts, ranked cards with score bars, Plotly coverage map with the mission envelope, gaps panel, filter chips.
- [ ] **7.4** **Investigation detail**: summary with citations, what was tested, first table rows, documents, publications, related investigations, copy-citation button.
- [ ] **7.5** **Compare**: 2–3 columns, "same and different" paragraph, highlight-differences toggle.
- [ ] **7.6** **Ask FireLens**: streamed answer, citation chips, evidence panel (text chunks + SQL rows), suggested questions.
- [ ] **7.7** **Export dialog**: format toggle, include options, live preview.
- [ ] **7.8** **Cold-start state**: the page shows instantly; "waking the data service" steps while `/meta` loads.
- [ ] **7.9** Accessibility (keyboard, labels, contrast) and a layout that works on phone screens.
- [ ] **7.10** Switch from mocks to the real API through one environment variable. *Done when:* all screens work against the local API.
- [ ] **7.11** *(Stretch)* Data status screen: pipeline stages, review queue, snapshot history, "Sync now".

## Phase 8: Quality (Both)

- [ ] **8.1** 15 gold questions with known answers from the reports. Run them through `/chat`. Pass mark: at least 13 correct and cited.
- [ ] **8.2** Check every number on screen traces back to a row or a computation. Check every DOI link opens.
- [ ] **8.3** End-to-end smoke test: profile → rank → open investigation → compare → ask → export.

## Phase 9: Azure infrastructure (Cloud track; Claude Code writes `infra/` scripts, a Person runs them)

- [ ] **9.1** Resource group `firelens-rg` in the chosen region. Log Analytics workspace + Application Insights.
- [ ] **9.2** Storage account `firelensdata`, Blob container `snapshots`. Upload snapshot v1 and `latest.json`.
- [ ] **9.3** Azure OpenAI resource `firelens-aoai`, with a chat deployment (GPT-4.1 mini or GPT-4o mini) and an embedding deployment.
- [ ] **9.4** Container Apps environment `firelens-env`.
- [ ] **9.5** Container App `firelens-api`:
    - image from GHCR; external ingress on port 8000; 0 to 2 replicas;
    - managed identity with Storage Blob Data Reader and Cognitive Services OpenAI User roles;
    - environment variables set.
- [ ] **9.6** Static Web App `firelens-web` linked to the repo's `web/` folder, with the API base URL set as a build variable.
- [ ] **9.7** Monthly budget alert (e.g. $20).
- [ ] **9.8** *(Optional)* Put 9.1–9.7 in one `az` CLI script or a Bicep file, so it can be rebuilt.

## Phase 10: CI/CD (Claude Code)

- [ ] **10.1** GitHub Action on `main`: build `firelens-api` and `firelens-sync`, push to GHCR, update the Container App.
- [ ] **10.2** Static Web Apps deploy workflow (Azure generates it), with build variables.
- [ ] **10.3** Store secrets in GitHub (deployment token, Azure credentials through OIDC). Nothing secret in the repo.

## Phase 11: Domain and go-live (Person, with Claude Code's checklist)

- [ ] **11.1** GoDaddy DNS:
    - `www` CNAME to the Static Web App default hostname, plus its validation TXT record;
    - `api` CNAME to the Container App, plus its `asuid.api` TXT record.
- [ ] **11.2** Add both custom domains in Azure and issue the free managed certificates.
- [ ] **11.3** Forward the bare domain to `https://www.` (GoDaddy forwarding), or move DNS to an Azure DNS zone.
- [ ] **11.4** Update CORS to the final domain. Smoke-test from a phone on mobile data.
- [ ] **11.5 = G2** Live on the custom domain. Keep the Azure default URLs as a backup link.

## Phase 12: Sync job (Data + Cloud tracks)

- [x] **12.1** *(Claude Code)* `sync/` entry point: catalogue diff by version and release date → harvest only what changed → normalize → precompute → new snapshot → update the pointer. Investigations with unreviewed column maps are added but flagged.
- [x] **12.2** *(Person)* Create the Container Apps Job `firelens-sync`: cron for 03:00 PKT, manual trigger allowed, Storage Blob Data Contributor role.
- [x] **12.3** *(Both)* Run it once by hand. *Done when:* the API swaps to the new snapshot within 15 minutes and the badge date changes.

## Phase 13: Hardening (Both)

- [ ] **13.1** Error, empty and loading states on every screen, including the cold start and "no matching data".
- [ ] **13.2** A light load test on `/rank` and `/chat`. Check the cold start takes under 10 seconds.
- [ ] **13.3** Review logs and costs in Application Insights. Confirm the budget alert works.
- [ ] **13.4** Tag the release `v1.0-submission`. No risky changes to `main` after this tag.

## Phase 14: Submission (Person; Claude Code drafts the text)

- [ ] **14.1** `README.md`: what it is, live URL, screenshots, architecture image, how to run, data credits.
- [ ] **14.2** `REFERENCES.md`: every PSI investigation used (with DOI), the challenge resources, models, libraries, GoDaddy, Azure, and any icons or fonts.
- [ ] **14.3** A note on how AI was used, both in the product and in building it.
- [ ] **14.4** Demo: 7 slides, in English. Slide order:
    1. title
    2. problem
    3. the Moon-base gap
    4. how it works
    5. walkthrough
    6. validity
    7. impact
- [ ] **14.5** *(Optional)* A 30-second screen recording, with English subtitles if the narration isn't in English.
- [ ] **14.6** Fill the project page: summary, links (live URL, repo, demo), NASA data used, references; tick both agreement boxes.
- [ ] **14.7 = G3** Submit by 22:30 PKT. Confirm it shows as submitted.

## Phase 15: After submission (Person)

- [ ] **15.1** Keep the site live through January 2027, when global judging finishes: scale to zero, nightly sync on, budget alert on.
- [ ] **15.2** Check `/meta` and costs weekly. Only fix things that are broken; no redesigns on the judged version.

---

## Critical path
0.2 → 0.3 → 2.1 → 2.2 → 3 → 4 (5 tables) → 5 → **G1** → 6.10 + 7.10 → 9 → 10 → 11 → **G2** → 8 → 14 → **G3**

## If behind schedule, cut in this order
1. Data status screen (7.11) and sync job (12): keep the manual snapshot.
2. Export JSON format (keep CSV).
3. Compare screen (keep the Explorer and Investigation screens).
4. The streaming trace panel (keep the plain cited answer).
5. Custom domain (submit the Azure URL).

Never cut: real PSI data, citations, the coverage map, and the live URL.
