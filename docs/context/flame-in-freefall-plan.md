# Flame in Freefall — Project Plan (NASA Space Apps 2026)

Nov 14, 2026 · @Qambar

We build **FireLens**: a web dashboard that turns NASA's PSI microgravity-combustion investigations into ranked, explained fire-safety answers for a chosen crew environment (Moon base, pressurized rover, spacecraft). Submission closes **Sunday 15 Nov, 23:59 local time** — about 34 hours from the start of this plan.

## The challenge in brief

**What NASA asks for.** An SI-powered, web-based dashboard that summarizes, ranks and interprets the combustion investigations in NASA's Physical Sciences Informatics (PSI) repository. Difficulty is rated Intermediate/Advanced.

**What it may let users do** (all optional, but they are our feature list):

- Find the investigations most relevant to fire safety in spacecraft, stations, lunar/Martian bases and pressurized rovers.
- Extract data that supports predictive modeling of flammability and fire scenarios.
- Highlight research that informs next-generation fire-safety controls and equipment.
- Optionally, show Earth applications (water-mist extinguishers, smoke detectors, firefighter gear).

**Hints worth designing around:**

- Audience: professors, graduate and undergraduate students, aerospace researchers and engineers.
- Attributes to surface: objectives; fuels (incl. sample/burner shape and size); test conditions (oxygen, airflow); what varied between tests; sensors and measurements; similarities and differences across investigations.
- Hardware families group the studies: ACME (gaseous flames, CIR); FLEX/FLEX-2/CFI (fuel droplets, MDCA in CIR); BASS/BASS-II/SPICE/SLICE (solid and gaseous fuels, MSG flow duct).
- The design driver: Moon base and rover cabins are expected at **≥30% O2 and ≤10.2 psi**, versus 21% at 14.7 psi on Earth and 100% at 4.3 psi in a suit. That makes materials much more flammable.
- PSI has **no partial-gravity data yet** (LUCI and FM2 are future). E-FIELD Flames mimics it; 1g and µg results can bound it. Rockets and propellants are out of scope.

**How it is judged.** Five criteria, each scored 1–5: Impact, Creativity, Validity, Relevance (NASA data must be integral, not decoration) and Presentation. The demo is either **7 slides max** or a **30-second video**, in English. Every external resource goes in the References field.

**One-line pitch:** *Pick "Moon base, 34% O2, 0.7 atm" and FireLens ranks the ISS experiments that matter, shows where NASA's tested conditions stop short of that cabin, and answers questions with citations to the exact test rows.*

## Websites, not documents: what the data really is

The resource links being websites is good news, not a problem. The one that matters, PSI, is a web app sitting on a **public JSON API with CC0-licensed CSV and PDF files**. We checked it live on 14 Nov: no login is needed to search or download. The other nine links are context pages (history, lessons learned, spin-offs) that feed the story, not the numbers.

**What sits behind the PSI website** (checked on BASS, FLEX, CFI-G and others):

| Layer | Endpoint (relative to psi.nasa.gov) | Format and size | What we use it for |
| --- | --- | --- | --- |
| Catalogue | `/geode-py/ws/repo/search?term=combustion&source=psi&type=investigation` | JSON; 26 hits (about 22 are combustion), 26 fields each: Objectives, Approach, Hypothesis, Research Impacts, Hardware, Keywords, Related Investigations, Publications | Investigation cards, summaries, embeddings |
| Investigation detail | `/geode-py/ws/repo/investigations/PSI-<n>` | JSON: DOI, license (CC0-1.0), every file with folder and size | File manifest, citations |
| Experimental tables | `/geode-py/ws/studies/PSI-<n>/download?file=<name>&version=<v>&redirect=false` | Returns a short-lived signed S3 link to a CSV; 2 to 1,016 rows per table | The numbers: fuel, O2, pressure, flow, outcome |
| Documents | Same manifest: Reports, Science Documents, Presentations, Engineering Documents | PDF/DOCX, typically 0.5–9 MB each | Text corpus for grounded answers |
| Raw data | Raw Data folders | Video and images; up to about 2 TB per ACME investigation | Do not download; link out |

The experimental tables are the gold. The ones we sampled already hold **2,400+ test rows**: CFI-G 1,194 (normal + inverse flames), SPICE 469, FLEX 274, BASS-II 129, BASS 123, SAME-R 109, CFI 87, ACME BRE 18, FLEX-2 8, SAFFIRE-III 2.

**How this changes the plan:**

1. **Build a harvester, not a reader.** One Python script pulls the catalogue, every investigation manifest, every experimental-table CSV and the report PDFs into a dated snapshot. The dashboard reads the snapshot, not PSI: the detail endpoint is slow (23 parallel calls took over a minute) and signed links expire. A nightly sync keeps the snapshot current (see Data freshness).
2. **Normalization is the hard, valuable part.** Every table has its own columns and units. FLEX writes oxygen as a mole fraction and pressure in mmHg; BASS-II writes "Calibrated initial O2 % by vol"; ACME BRE packs "21; 26.5; 40" into one cell; FLEX-2 stores ranges like "1.5 - 5". We map all of them into one schema with an LLM-proposed, human-checked column map plus code for unit conversion. This is where the "SI" earns its name.
3. **Numbers come from code, words from the model.** Condition ranges, counts and rankings are computed from the CSVs. The LLM writes summaries and explanations from the JSON fields and PDFs, and must cite the PSI accession and DOI.
4. **Skip raw data.** Terabytes of video add nothing in 34 hours. Show representative images and link to PSI.
5. **Context pages become a small corpus.** Apollo 1, Apollo 13, Mir and the three Spinoff pages are scraped once into text for the "why it matters" and Earth-applications views.
6. **Freeze and cite.** CC0 lets us host our cleaned snapshot. PSI asks users to cite each dataset by its DOI (e.g. BASS: 10.60555/58h4-dy80); the dashboard prints the DOI on every card and export.

**Fallback if the API changes or blocks the cloud IP:** run the harvester from a laptop, commit the snapshot (CSVs + JSON are small) to the repo, and deploy from that.

## Product design: FireLens

FireLens is built around one control: the **mission profile**. The user picks the crew environment, and every view re-ranks and re-colors for it. That turns a pile of experiments into an answer to "what do we know about fire *here*?"

**Mission profiles (presets, editable):** Earth sea level (21% O2, 14.7 psi) · ISS cabin (\~21%, 14.7 psi) · Moon base / pressurized rover (≥30%, ≤10.2 psi) · spacesuit (100%, 4.3 psi) · custom (O2 %, pressure, airflow, gravity level).

**Primary users:** an aerospace engineer choosing cabin materials; a graduate student looking for validation data for a model; a professor comparing investigations for a course.

| View | What the user sees | Challenge objective it serves | Priority |
| --- | --- | --- | --- |
| Investigation Explorer | One card per combustion investigation: AI summary, fuel phase, hardware, prevention/detection/suppression tag, relevance score with a breakdown bar, DOI | Find the most relevant investigations | MVP |
| Condition Coverage Map | Every test row plotted by O2 vs pressure, colored by outcome (ignited, extinguished, cool flame), with the mission-profile box overlaid. Shows where NASA's tests stop short of the Moon-base cabin | Predictive modeling; shows gaps | MVP (the hero visual) |
| Compare | 2–3 investigations side by side: objectives, fuels and geometry, condition ranges, what varied, sensors; a generated "same / different" paragraph | Similarities and differences | MVP |
| Ask FireLens | Chat grounded in summaries, tables and reports; every claim cites accession, DOI and source file | Interpret findings | MVP |
| Data Export | The filtered, unit-normalized test table as CSV/JSON with a citation block | Support predictive modeling | MVP |
| Mission Safety Brief | One-page generated brief per profile: top 5 investigations, key findings, data gaps (no partial-g yet; LUCI and FM2 coming), suggested next tests | Inform next-generation controls | Stretch |
| Flammability boundary explorer | A simple, clearly labeled exploratory model (e.g. logistic regression) of ignition/extinction vs O2 and pressure, from FLEX and CFI-G | Predictive modeling | Stretch |
| Earth benefits | Water mist, smoke detector, fire attire, air tanks, linked to the Spinoff pages | Earth applications | Stretch |

**What makes it creative:** most teams will build a search page with a chatbot. Our edge is (1) the mission-profile re-ranking, (2) the coverage map that shows the *gap* between tested and future cabin conditions, and (3) answers traceable to the exact test row.

**Scope guard:** rockets and propellants are out. Partial gravity is shown as a gap and as bounds (µg vs 1g), never as invented data.

## Data pipeline

The pipeline runs by hand first (target: first snapshot by Sunday 02:00), then every night as a sync job. Each run writes a dated snapshot that the API loads from Blob Storage.

1. **Harvest the catalogue.** Call the search endpoint with `term=combustion`, keep rows whose Research Area is Combustion Science (drop the solder and STDCE hits). Save raw JSON.
2. **Harvest manifests.** For each accession, fetch `/repo/investigations/PSI-<n>`; save DOI, license, hardware, and the file list (name, folder, size, version). Run with a small concurrency limit (3–4) and retries; the endpoint is slow.
3. **Download experimental tables.** For each file in the Experimental table folder, call the download endpoint with `redirect=false`, then fetch the signed S3 URL immediately. Store CSVs as-is under `raw/PSI-<n>/`.
4. **Download documents selectively.** Only Reports and Science Documents under \~20 MB (final reports, conference papers). Extract text with PyMuPDF / python-docx; keep page numbers for citations.
5. **Scrape the context pages** (Apollo 1, Apollo 13, Mir, three Spinoffs, the NASA combustion page, the Researcher's Guide) to plain text with source URLs.
6. **Normalize.** For each CSV, an LLM proposes a column map to the unified schema below; a teammate checks it in a YAML file (`maps/PSI-69.yaml`). Code applies the map, converts units and splits multi-value cells.
7. **Validate and freeze.** Pandera checks (O2 fraction in 0–1, pressure > 0, no duplicate test IDs). Write `tests.parquet`, `investigations.json`, `chunks.jsonl` and a `SNAPSHOT.md` with the date and counts.

**Unified test schema (one row per test):**

| Field | Type / unit | Example source columns |
| --- | --- | --- |
| accession, investigation, test\_id | text | "FLEX Test #", "Test", "Sample #" |
| test\_date | date | "Test Date", "Date" + "GMT" day-of-year |
| fuel, fuel\_phase | text; solid / liquid / gas | "Fuel", "Fuel Sample Material", "Fuel Bottle" |
| sample\_geometry, sample\_size\_mm | text; mm | "PMMA sphere 2 cm", "Droplet initial diameter; mm", "Nozzle (mm)" |
| o2\_fraction | 0–1 | "O initial ambient composition; mole fraction", "Calibrated initial O2 % by vol" ÷ 100, "XO2" |
| pressure\_kpa | kPa | "Ambient pressure; mmHg" × 0.1333, "Pressure" (atm) × 101.325, "approx p (bar)" × 100 |
| diluent | text | N2 / He / CO2 mole fractions |
| flow\_cm\_s, flow\_direction | cm/s; opposed / concurrent / quiescent | "Air Rate (cm/s)", "Flow Velocity (cm/s)", "Direction" |
| outcome | ignited / extinguished / cool flame / failed / unknown | "Test end", "Cool flame?", "Hot ignition", "Self-ext or flow term" |
| metrics | JSON of name → value + unit | burn time, extinction diameter, burning rate, peak burner T |
| source\_file, source\_row, doi | text | provenance for every number |

**Investigation record:** accession, acronym, title, DOI, hardware, platform, sub-area, fire-safety category (prevention / detection / suppression), related investigations, condition ranges computed from its tests, file counts and sizes, text fields, and the AI summary.

Where a table cannot be mapped cleanly in time (e.g. SAFFIRE-III's 2 rows, FLEX-2's ranges), keep it as investigation-level metadata rather than forcing bad rows.

## Data freshness: snapshot plus nightly sync

FireLens shows a reviewed snapshot of PSI and keeps it in sync, so no one sees silently stale data. PSI itself is not real-time: it holds finished ISS experiments. What changes is the occasional new investigation or dataset version: BASS moved to version 4 in March 2025, the CFI-G tables were added in November 2025, and PSI-117 was released in June 2026.

**Why not read PSI live on every request**

- **Speed:** the detail endpoint is slow; 23 lookups took over a minute.
- **Review:** each table's column map must be checked before its numbers can be compared; that cannot happen mid-request.
- **Links expire:** CSV downloads come as short-lived signed links.
- **Reliability:** judging runs into January; PSI being slow or changing must not break the demo.
- **Citable results:** "PSI as of 15 Nov, BASS version 4" is reproducible.

**How freshness is kept**

1. **Nightly sync job** (Azure Container Apps Job, 03:00 PKT): reads the catalogue, compares each accession's version and release date with the current snapshot, and re-downloads only what changed.
2. **New releases appear at once, flagged:** text, DOI and link show immediately, marked "new, auto-mapped, under review". Their numbers join the rankings once the column map is checked.
3. **No redeploy:** each run writes `snapshots/<timestamp>/` to Blob Storage and updates `latest.json`. The API checks the pointer every 15 minutes and swaps the data in memory. The last good snapshot stays as a fallback, and a copy baked into the image covers a storage outage.
4. **Live freshness badge:** the API checks PSI's fast search endpoint about once an hour. The UI shows "Data synced 15 Nov 03:00 · PSI checked 6 min ago · 0 new releases", with a banner linking to anything not yet synced.
5. **Provenance on every card:** dataset version, DOI and a link to the live PSI page.
6. **"Sync now" button** for admins: trigger it on camera in the demo video.

**Line for judges:** *FireLens mirrors PSI nightly and checks it live. Numbers go through review before we show them, because a wrong unit on an oxygen value is worse than a one-day delay.*

## SI layer: summarize, rank, interpret

The rule that keeps it valid: **the model writes, the code counts.** Every number on screen is computed from the snapshot; the LLM only turns facts it is given into readable text, and must cite them.

**1. Summarize (precomputed, not live).** For each investigation, the LLM receives the catalogue fields, computed condition ranges and the first pages of its final report. It returns structured JSON: objective (1 sentence), fuels and geometry, conditions tested, what varied, sensors, 3 key findings each with a source, and a prevention/detection/suppression tag. A teammate spot-checks all \~20 summaries. Cost: one batch run, cached.

**2. Rank (transparent formula, model only explains it).** Relevance to the chosen mission profile =

```latex
R = 0.40\,C + 0.25\,F + 0.20\,M + 0.15\,D
```

- C = condition proximity: share of the investigation's tests within a tolerance of the profile's O2, pressure and airflow (computed from the unified table).
- F = fuel realism for habitats: solids such as fabrics and plastics score high, research gases lower.
- M = fire-safety category match to the user's goal (prevention, detection, suppression).
- D = data richness: test rows, analyzed data, reports available.

The card shows the four bars, so judges can see why BASS-II outranks ACME s-Flame for a cabin-materials question. Weights are exposed as sliders.

**3. Interpret (Ask FireLens, RAG).** Chunks = investigation summaries + report text + context pages, embedded once. For a question, retrieve the top chunks plus matching rows from the test table (a filter the model writes as JSON, executed by code). The answer must cite `[PSI-69, FLEX, DOI, file p.12]`; if retrieval finds nothing, it says so. No answer about rockets or invented partial-g values.

**4. Compare.** Side-by-side fields come straight from the records. The model writes one "same / different" paragraph from those fields only.

**5. Similar investigations.** Cosine similarity of summary embeddings plus shared hardware and fuel phase → a "related" strip on each card (it should rediscover the ACME, MDCA and SPICE-duct families on its own: a good validity check).

**6. Stretch: exploratory flammability model.** Logistic regression of ignition or extinction against O2 fraction and pressure, per fuel class, on CFI-G and FLEX rows. Labelled "exploratory, not for design", with the training row count shown.

**Quality check before demo:** 15 gold questions with known answers from the reports (e.g. "Which experiments used helium as a diluent?"). Pass mark: correct and cited on at least 13.

### What is embedded, what is queried, what is only linked

Embeddings carry the meaning of text; they are poor at numbers (0.30 vs 0.34 O2 look alike). So text is embedded, numbers are queried with SQL, and heavy or external material is linked.

| Data | Stored as | Reaches the user as |
| --- | --- | --- |
| Investigation text fields: objectives, approach, hypothesis, research impacts, keywords | **Vectors**, one chunk per field | Quoted in chat answers, with a citation |
| AI summaries | **Vectors** | Card text |
| Report and paper text | **Vectors**, 500–800-token chunks with page numbers | Cited as "BASS final report, p. 7" |
| Context pages (Apollo, Mir, spin-offs) | **Vectors** | Story and Earth-benefits view |
| Test rows: fuel, O2, pressure, flow, outcome, metrics | **Table** (DuckDB over Parquet), queried with SQL | Coverage map, ranking, CSV export, exact rows in chat |
| Condition ranges, rank scores | Computed per request | Score bars on cards |
| DOI, license, hardware, version, file manifest | **JSON records** | Printed on cards and exports |
| Raw video and images (TB), report files, publications | **Not stored**, except thumbnails | **Links only:** PSI page, doi.org, publication DOI |

Every vector carries metadata: accession, DOI, source file, page, dataset version, PSI URL. That is what lets each sentence end with a citation like **\[PSI-25 · BASS-II · doi · report p. 4\]**; clicking it opens NASA's page directly, never a copy on our server.

## Architecture and tech stack

&#91;embedded content: FireLens architecture · offline harvest, live Azure app\]

The sync job runs by hand first, then nightly, and writes dated snapshots to Blob Storage. The API loads the latest one, checks PSI hourly for new releases, and calls the model only for chat.

Team whiteboard of this layout and the request walkthrough: [FireLens — Deployment and Request Flow](https://claude.ai/artifact/8MYSF26xRTyDyqycXYTqZ8).

| Layer | Choice | Note |
| --- | --- | --- |
| Harvest and ETL | Python 3.12, httpx (async, retries), pandas, Pandera, PyMuPDF, python-docx | Runs locally or in GitHub Actions |
| Storage | Parquet + DuckDB; LanceDB or FAISS for vectors | Loaded from Blob Storage via a latest.json pointer; a baked-in copy as fallback |
| SI | Azure OpenAI chat + embedding models; a small hand-written RAG module | Precompute summaries; live calls only for chat |
| API | FastAPI, Uvicorn, Docker | Endpoints: /investigations, /rank, /compare, /tests, /chat, /export |
| Frontend | React + Vite + TypeScript, Plotly.js, Tailwind | Coverage map, cards, compare, chat |
| Dev tooling | GitHub, GitHub Actions, GitHub Copilot (Microsoft offer) | One repo, CI deploys both apps |
| Hosting | Azure Static Web Apps + Container Apps; GoDaddy DNS | See the deployment section |

**Repo layout:** `harvest/` (harvest.py, normalize.py, maps/\*.yaml) · `snapshot/` (tests.parquet, investigations.json, chunks.jsonl, SNAPSHOT.md) · `api/` (main.py, rank.py, rag.py, Dockerfile) · `web/` (React app) · `REFERENCES.md`.

## Deployment: Microsoft Azure + GoDaddy domain

Azure runs the whole app; GoDaddy supplies the domain and DNS. The two Global Offers, as announced on Space Apps Connect: **GoDaddy** gives every participant a free domain and one year of website hosting; **Microsoft** offers Azure, GitHub Copilot, Microsoft Copilot, Planetary Computer and Teams. The exact Azure credit and claim links sit on the Global Offers page, which needs your Space Apps login. Some offers ask for a card for verification only; nothing needs to be bought.

**Target setup**

| Resource (in `firelens-rg`) | Azure service | What it does |
| --- | --- | --- |
| `firelens-web` | Static Web Apps, Free plan (no container) | Serves the React + Plotly site from Azure's edge; builds from GitHub; free TLS on custom domains |
| `firelens-api` | Container App, **Docker image 1** (Python, FastAPI, DuckDB, LanceDB) | Search, rank, compare, chat, export, freshness check; scale to zero, max 2 replicas |
| `firelens-sync` | Container Apps Job, **Docker image 2** (harvester + normalizer) | Nightly sync at 03:00 PKT, plus the manual "Sync now" trigger |
| `firelensdata` | Storage account, Blob container `snapshots/` | Dated snapshots + `latest.json` pointer |
| `firelens-aoai` | Azure OpenAI | Two deployments: chat (GPT-4.1 mini or GPT-4o mini) and embeddings (text-embedding-3-small) |
| Images | GitHub Container Registry | Free; avoids a registry fee |
| Identity | Managed identity on the API and job | Reaches OpenAI and Blob with no keys in code |
| Monitoring | Log Analytics + Application Insights; budget alert | Errors, usage, cost guard |
| DNS | GoDaddy (or an Azure DNS zone) | `www` → web app, `api` → API |

Two Docker images, one static site; no virtual machines and no database server.

**Step by step (owner: cloud lead)**

1. Log in to spaceappschallenge.org → 2026 Global Offers. Claim GoDaddy and Microsoft. If Azure sign-up rejects your country or region, post in the Global Offers discussion on Space Apps Connect right away.
2. Create resource group `firelens-rg` in one region that offers the Azure OpenAI models you need (check model availability first).
3. Create `firelens-aoai` and deploy the chat and embedding models. Run summaries and embeddings once, locally, into the first snapshot.
4. Create storage `firelensdata`; upload the first snapshot to `snapshots/<timestamp>/` and write `latest.json`.
5. Push both images to GitHub Container Registry from GitHub Actions.
6. Create the Container Apps environment, then `firelens-api` (external ingress, port 8000, min 0 / max 2) and `firelens-sync` (scheduled job, cron for 03:00 PKT, manual trigger allowed).
7. Turn on managed identity for both; grant them access to the OpenAI resource and the storage account.
8. Create the Static Web App linked to the repo's `web/` folder; set the API base URL as a build variable.
9. Domain and DNS (see "Domain: GoDaddy plus Azure"): `www` CNAME to the web app plus its validation TXT; `api` CNAME to the Container App plus its `asuid.api` TXT and a free managed certificate.
10. Lock down: CORS allows only the `www` domain; per-IP rate limit on `/chat`; monthly budget alert.
11. Smoke test from a phone on mobile data, run "Sync now" once, then freeze the deployment for the demo.

**Using the GoDaddy hosting year:** not needed for the app. Optionally host a one-page static "About FireLens" there; otherwise leave it.

**Keep it alive through judging.** Finalists are named in December and winners in January 2027, so judges may open the link weeks later. Scale-to-zero, precomputed summaries and a chat rate limit keep that period nearly free; the domain is already paid for a year.

### AI usage and credit estimate

Azure OpenAI is chosen because Microsoft's offer gives us Azure: one subscription for hosting and models, managed identity instead of API keys, and one credit balance. It is not a lock-in: all model calls go through one `llm.py` wrapper, so any OpenAI-compatible provider can replace it.

Prices used (per million tokens): GPT-4.1 mini $0.40 in / $1.60 out; GPT-4o mini $0.15 in / $0.60 out; text-embedding-3-small $0.02.

| Use | Tokens (rough) | Cost on GPT-4.1 mini |
| --- | --- | --- |
| Column mapping, \~15 tables | \~50k in, 15k out | under $0.05 |
| Investigation summaries, \~22, run about 3 times | \~0.7M in, 0.1M out | about $0.45 |
| Embeddings, reports + fields, built twice | \~3M | about $0.06 |
| Chat, \~2,000 questions (team, testers, judges); \~6k in, 600 out each | 12M in, 1.2M out | about $6.70 (about $2.50 on GPT-4o mini) |
| **Total** |  | **about $3–8** |

Azure for Students alone gives $100 of credit; the Space Apps offer may add more. The model is the smallest cost. Keep hosting cheap too: scale to zero, GitHub's free registry, and the chat rate limit.

### Domain: GoDaddy plus Azure

Azure hosts everything; GoDaddy only supplies the name. Azure cannot sell us the domain instead: App Service domains are not available on free-trial or credit-based subscriptions.

- **Azure only:** use the free auto-generated web address with HTTPS. Zero setup, but a random-looking name.
- **GoDaddy name + Azure hosting (chosen):** a memorable address for slides and the video. GoDaddy cannot point the bare domain (no `www`) straight at Azure, so either forward it to `www` with GoDaddy forwarding, or move the nameservers to an Azure DNS zone, which creates the apex records for you.
- If time runs short on Sunday, skip the domain and submit the Azure address; nothing else depends on it.

## Request walkthrough: one user, start to finish

Scenario: a materials engineer checks which cabin fabrics have been tested near Moon-base air.

1. **Opens www.firelens.space.** DNS points to the Static Web App, which serves the site from the nearest Azure edge over HTTPS. The API is not involved yet.
2. **The page calls `/meta`.** If the API is idle, it wakes in a few seconds (the UI shows "waking up"). At start-up the API loaded the latest snapshot from Blob Storage into memory. It returns the snapshot date, counts and the cached PSI freshness check.
3. **Picks "Moon base" (34% O2, 70 kPa).** `/rank` runs SQL over the test table, scores each investigation against those conditions, and attaches the precomputed summaries and DOIs. No model call; about 100 ms.
4. **Opens the coverage map.** `/tests` returns the rows; the browser draws the chart. No model call.
5. **Asks: "Which fabric tests burned above 30% oxygen, and at what airflow?"** `/chat` checks her rate limit; embeds the question (one cheap call); finds the 8 closest chunks; lets the chat model request rows through a structured filter such as `{fuel_phase: solid, o2_min: 0.30}`, which the API runs as SQL; sends question, chunks and rows to the model with citation rules; streams back an answer with clickable citations.
6. **Clicks a citation.** Her browser goes straight to doi.org or the PSI page, not through our server.
7. **Exports the filtered rows** as a CSV whose header lists the DOIs and the snapshot date.
8. **At 03:00 the sync job runs.** If PSI changed, it writes a new snapshot and updates the pointer; within 15 minutes the API swaps it in and the badge shows the new date.

## Team roles and timeline

Four roles, one owner each; with fewer people, merge Cloud & story into the SI lead. Given your AI-infrastructure background, the SI lead role fits you best.

| Role | Owns | Hands off |
| --- | --- | --- |
| Data lead | Harvester, normalizer, column-map YAMLs, snapshot, nightly sync job | Frozen snapshot, Sun 02:00 |
| SI lead | Summaries, ranking formula, embeddings, RAG, gold questions, Azure OpenAI | /rank, /compare, /chat endpoints |
| Frontend lead | React app: explorer, coverage map, compare, chat panel, export | UI wired to the API |
| Cloud & story lead | Global Offers, Azure resources, GoDaddy DNS, REFERENCES.md, slides, video, submission form | Live URL and submitted project |

&#91;embedded content: Hackathon timeline · three gates: data freeze, live URL, submission\]

Three gates hold the plan together: the data freeze at Sun 02:00, the live custom-domain URL at 14:00, and pressing submit by 22:30 with 90 minutes of buffer. Sleep in two shifts between Sun 02:00 and 08:00 so someone is always awake; the frontend works on mock JSON until the snapshot lands.

## Submission package

Submit from the Project tab of the team page before Sunday 23:59 local; aim to press submit by 22:30. All teammates must be registered for the same local event and listed on the team page before submission closes. Read the Project Submission Guide once on Saturday for the exact fields.

**Demo: a 7-slide deck (required form), plus an optional 30-second screen recording.**

1. Title: FireLens, team, challenge name, live URL.
2. The problem: fires in Apollo 1, Apollo 13, Mir; 2,400+ ISS test rows that are hard to find, compare and interpret.
3. The Moon-base gap: the coverage map with the ≥30% O2 / ≤10.2 psi box against tested conditions.
4. How it works: the architecture diagram (PSI API → snapshot → normalizer → SI → dashboard on Azure).
5. Live walkthrough stills: pick profile → ranked cards → compare → cited answer.
6. Validity: "model writes, code counts", citation on every claim, gold-question score, freshness badge and nightly sync, limits (no partial-g data).
7. Impact and next steps: material selection, model validation, Earth spin-offs; add LUCI/FM2 data when PSI publishes it.

**References field must list:** each PSI investigation used with its DOI; the challenge resource pages; the models used; open-source libraries; GoDaddy and Microsoft Azure; any icon or image source. Write it as you go in `REFERENCES.md`.

**Judging criteria checklist**

| Criterion | What judges must see | Evidence in FireLens |
| --- | --- | --- |
| Impact | A real problem for real users | Moon-base material choice; researchers finding validation data |
| Creativity | Not "just a chatbot" | Mission-profile re-ranking; coverage-gap map; row-level citations |
| Validity | Sound science, works, usable | Computed numbers, unit-checked schema, gold-question score, live URL |
| Relevance | NASA data is the core | Every view is built from PSI tables and reports; DOIs shown |
| Presentation | Clear story | 7 slides that follow problem → gap → solution → proof |

## Risks and fallbacks

| Risk | Likelihood | Fallback |
| --- | --- | --- |
| PSI API slow or blocks cloud IPs | Medium | Harvest from a laptop; commit the snapshot to the repo; at runtime only a cached, hourly catalogue check |
| Normalization takes too long | High | Fully normalize the 5 richest tables first (CFI-G, SPICE, FLEX, BASS-II, BASS); keep the rest as investigation-level metadata |
| Azure sign-up, region or model access blocked | Medium | Ask in Space Apps Connect; meanwhile build against any OpenAI-compatible API behind one `llm.py` wrapper; worst case, deploy the static frontend with precomputed answers only |
| LLM invents numbers or findings | Medium | Numbers only from code; citations required; refuse when retrieval is empty; spot-check all summaries |
| Running out of time for the UI | Medium | Explorer + coverage map + compare are the MVP; chat and export are next; everything else is stretch |
| DNS or TLS not ready for the demo | Low–Medium | Point DNS by Saturday night (propagation); the Azure default URLs work as a backup link in the submission |
| Costs grow during the judging months | Low | Scale to zero, rate-limited chat, budget alert |
| Team member not registered to the same local event | Low but fatal for global judging | Check the team page Saturday afternoon |

## Sources

All checked on 14 Nov 2026.

- [Flame in Freefall challenge page and Resources tab](https://www.spaceappschallenge.org/2026/challenges/flame-in-freefall/)
- [PSI Data Repository: Combustion Science search](https://psi.nasa.gov/physci/repo/search?q=combustion)
- [PSI-26 BASS investigation page](https://psi.nasa.gov/physci/repo/data/investigations/PSI-26) (example of manifest, experimental table and DOI)
- [NASA Combustion Science (Glenn)](https://www.nasa.gov/glenn/glenn-expertise-space-exploration/physical-sciences-program/combustion-science/)
- [A Researcher's Guide to ISS Combustion Science](https://www.nasa.gov/missions/station/a-researchers-guide-to-combustion-science/)
- [Apollo 1 lessons learned](https://sma.nasa.gov/sma-disciplines/accllp/apollo-1) · [Apollo 13 lessons learned](https://sma.nasa.gov/sma-disciplines/accllp/apollo-13) · [Fire aboard Mir](https://www.nasa.gov/history/25-years-ago-fire-aboard-space-station-mir/)
- Spinoffs: [Fireman's air tanks](https://spinoff.nasa.gov/node/9582) · [Fire detector](https://spinoff.nasa.gov/node/9407) · [Fire attire](https://spinoff.nasa.gov/node/9918)
- [Space Apps Connect: Global Offers are live (GoDaddy, Microsoft and others)](https://github.com/nasa/spaceapps/discussions/2058)
- [Judging and Awards Guide](https://www.spaceappschallenge.org/resources/judging-awards-guide/)
- [2026 Space Apps home: dates and submission window](https://www.spaceappschallenge.org/2026/)

* [Azure AI model pricing (azurespeed)](https://www.azurespeed.com/AzureAiModelPricing) · [GPT-4.1 mini pricing (cloudprice)](https://cloudprice.net/models/gpt-4.1-mini) · [Azure OpenAI pricing (inference.net)](https://inference.net/content/azure-openai-pricing-explained/)
* [Microsoft Q&A: App Service domains not available on credit-based subscriptions](<https://learn.microsoft.com/en-us/answers/questions/1663421/the-subscription-(subscriptionid)-is-not-eligible>)
* [Custom domains with Azure Static Web Apps](https://learn.microsoft.com/en-my/azUre/static-web-apps/custom-domain) · [Apex domain with Azure DNS](https://learn.microsoft.com/is-is/azure/static-web-apps/apex-domain-azure-dns)
* [Azure for Students $100 credit (Space Apps Mountain View event page)](https://luma.com/9ndjo3rj)
