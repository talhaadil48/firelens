# Decisions and unresolved review items

1. *(Superseded by 11.)* Only the build checklist was supplied. The referenced `flame-in-freefall-plan.md`
   and original `CLAUDE.md` were not supplied. This repository records a provisional,
   explicit schema instead of pretending the missing pipeline specification was read.
2. FLEX has one experimental CSV; CFI-G has two (normal/inverse flames). Download
   all three. FLEX needs cp1252 decoding; retain original bytes and record encoding.
3. Five metadata fixtures come from public PSI manifests. Findings only repeat the
   catalogue title with its source field; there are no made-up physical conclusions.
   The empty tests response is intentional until Phase 4 normalization.
4. Frozen contract routes use `/investigations/{accession}` (the same identifier as
   the plan's `{id}`). `/profiles` is an additional typed route for shared UI config.
5. *(Superseded by 12.)* Assign weights 0.40/0.25/0.20/0.15 to oxygen/pressure/flow/gravity respectively.
   The supplied checklist gave weights but not dimension definitions. This is a
   provisional design choice requiring human/science approval before real ranking.
6. *(Rover part superseded by 13.)* Earth/ISS use rounded illustrative values. Moon-base and spacesuit use the
   user-plan conditions, not official specifications. Rover was unspecified, so
   its conditions stay null. All scenarios are labelled illustrative.
7. No scores are computed in the Phase 2 server. Null never means zero relevance.
   No ranking or coverage inference is made from catalogue metadata.
8. `source_row` means original 1-based physical CSV row. PDF page is separate.
   Test IDs are unique within an investigation; use `(accession, test_id)` globally.
   Ranges/lists and ambiguous units require later reviewed maps and are not expanded.
9. Git commit identity follows the existing Windows Git configuration:
   `talhaadil48 <talhaadil48@icloud.com>`. Software copyright uses Talha Adil.
10. Do not require cloud accounts for Phase 2. The development server is local only;
    production LLM access, rate limits, sync, provisioning and deployment are later phases.
11. The project plan (`flame-in-freefall-plan.md`), UI concept (`ui-design/`) and
    deployment diagram (`deployment-flow.png`) are now in `docs/context/`. Contract v2
    aligns `api/models.py` with the plan's unified test schema: `o2_fraction`, `fuel`,
    `sample_geometry`, `sample_size_mm`, `test_date`, `diluent`, `metrics` (value plus
    original unit), and `outcome` / `flow_direction` enums. The investigation record gains
    catalogue text fields, a cited structured `summary`, publications and file counts.
12. Ranking follows the plan: R = 0.40 C + 0.25 F + 0.20 M + 0.15 D (condition proximity,
    fuel realism, fire-safety category match to `goal`, data richness). Tolerances,
    fuel-realism scores and the richness scale live in `config/profiles.yaml` as labelled
    design choices. An investigation without normalized tests is `metadata_only` with a
    null score, never zero.
13. The rover uses the plan's shared "Moon base / pressurized rover" envelope (≥30 % O2,
    ≤70 kPa, nominal 34 % / 70 kPa). Still illustrative, not a NASA requirement.
14. Responses carry `mode: mock | snapshot`. Snapshot v1 is committed and baked into the
    API image (the plan's fallback). Blob Storage `latest.json` loading follows after G2.
15. Vectors are stored as a NumPy array in the snapshot (`vectors/embeddings.npy` plus
    chunk ids) and searched by brute-force cosine similarity, instead of LanceDB. The
    corpus is a few thousand chunks at most, so exact search takes milliseconds, and
    dropping LanceDB and pyarrow cuts ~330 MB from the API image, which keeps the
    scale-from-zero cold start short on Container Apps.
16. The text corpus includes Reports and Science Documents (PDF/DOCX under 20 MB) from each
    manifest, downloaded to `raw/PSI-<n>/documents/` through the same signed-link flow
    (with the file's `version`). Text is extracted per page with PyMuPDF and chunked within
    a page, so every document chunk cites one file and page. No OCR: pages without a text
    layer are counted as empty, never guessed. Presentations, Engineering Documents and
    Raw Data are linked only. Investigation `documents` link to the PSI page, not a copy.
17. One snapshot is committed (`latest.json` plus the folder it names); local rebuilds stay
    ignored. A CI test fails if the pointer names an uncommitted folder, because the API
    image would otherwise crash at startup in a clean build.
18. Context pages that scrape to under 200 characters are logged as failures, not "ok".
    The HTML extractor no longer skips `<form>`: ASP.NET pages (the Apollo 1 and 13
    lessons-learned pages) wrap their whole body in one form.
19. Local `docker compose up` serves the committed snapshot with unreviewed rows included
    (responses carry a warning) and the web in API mode. The `dev` toolbox stays in mock
    mode so tests are unaffected. Production keeps `FIRELENS_ALLOW_UNREVIEWED=false`.
