# Phase 3 — collection and audit handoff

Branch: `feature/phase-3-harvest`, created from current `main` at `2d94386`.
Scope: all six Phase 3 implementation steps. No normalization, model inference,
scientific ranking, production synchronization or deployment has been implemented.

## Run it

From the repository root (PowerShell, bash or a terminal with uv available):

```text
uv sync --frozen
uv run python -m harvest.run
```

Or `make harvest` in a shell with Make. The command uses three workers (four is
available with `--workers 4`), retries transient errors and reuses an on-disk cache.
It never downloads bulk Raw Data.

Original files go to `raw/<UTC-run-id>/PSI-<number>/`. Tables retain their exact
bytes, including line endings and legacy encoding. Supporting documents go in
`documents/Reports/` or `documents/Science_Documents/`. Long/Windows-unsafe file
names are shortened deterministically; reports retain the full source filename.
The archive is deliberately ignored by Git. Code, configuration and audit reports
are committed; teammates run the command to download their own copy.

The default run contains:

```text
raw/<run-id>/
  catalogue/page-00000.json       original paginated catalogue responses
  catalogue/page-00100.json
  catalogue/combustion.json       exact research-area filter
  PSI-<number>/manifest.json      original metadata response
  PSI-<number>/inventory.json     DOI, version, license, hardware, selected file inventory
  PSI-<number>/*.csv              original experimental tables
  PSI-<number>/documents/         selected supporting documents
  PSI-<number>/harvest.json       per-investigation results
  context/                       NASA pages, guide PDF, extracted text, source receipts
  report.json                    machine-readable audit
  HARVEST_LOG.md                  counts, failures, caveats and timing
```

`raw/_cache/` stores content plus SHA-256/size receipts. Cache hits are checked
before reuse, versioned files have version-specific keys, and outputs are copied
rather than hardlinked. Completed run folders are immutable; use a new run ID.
Re-running uses the cache; an explicit partial run ID can be resumed. `--refresh` refreshes
catalogue/manifests/context. `--offline` forbids network requests and uses verified
cached content only. Do not use `--refresh` with `--offline`.

## What each plan point does

| Point | Implementation and verification |
| --- | --- |
| 3.1 | Paginate ALL PSI investigations, then retain exact `Research Area = Combustion Science`; preserve each original response. No fixed investigation count or search-keyword assumption. |
| 3.2 | Fetch every selected manifest with bounded concurrency, retry/backoff and verified cache. Retain full source file lists plus explicit DOI/version/license/hardware fields. |
| 3.3 | Deduplicate experimental table listings; resolve signed URLs and immediately fetch each CSV. Do not persist temporary URLs. Hash original bytes and record encoding/headers/CSV-record counts. |
| 3.4 | Select only Reports and Science Documents strictly below decimal 20 MB. Enforce both advertised and streamed size bounds. Other categories and restricted files are skipped/recorded; Raw Data is excluded. Source failures remain visible. |
| 3.5 | Capture Apollo 1, Apollo 13, Mir, NASA Spinoffs, combustion overview and Researcher's Guide context, including the linked guide PDF and its page-separated text. Preserve source URLs/retrieval receipts. Official challenge-page capture is attempted separately; selected NASA references are not claimed to be the complete official challenge list. |
| 3.6 | Write a dated folder, machine-readable report and human-readable harvest log. A partial run exits nonzero and cannot overwrite the last complete-run pointer. |

## Results and actual source gaps

The executed catalogue has **24 Combustion Science investigations** among 133 PSI
investigations. This supersedes the checklist's approximate count of 22.

The run saved **24 manifests, 22 experimental CSV files, 53 supporting documents,
and eight context topics** (including the Researcher's Guide PDF). Four investigations
(PSI-60, PSI-62, PSI-115 and PSI-117) list no experimental table; none was fabricated.
All listed, eligible experimental CSVs were saved. These counts are not counts of
independent experiments or scientifically reviewed test runs.

Two PSI-26 legacy report links returned HTTP 404:

- `PSI-26_Reports_SPICE_FinalReport.pdf`
- `PSI-26_Reports_BASS_FinalReport.pdf`

Version-specific requests also returned 404; the old manifest-linked NASA host
was unreachable. Those source failures have not been disguised as successful
copies or replaced with a different report. The aggregate harvest therefore stays
**partial**, even though the complete available CSV collection was downloaded.
The official challenge page also could not be captured in this environment; eight
explicit primary NASA context references were saved instead. This is reported as
a separate discovery limitation, not a claim that official resources were verified.

See [the executed harvest log](harvest/HARVEST_LOG.md) and
[the full audit report](harvest/report.json) for current run paths, hashes, file
inventories, source versions, durations, skip reasons and exact failures.

## Check the downloaded files

```text
uv run python -m harvest.verify raw/plan-aligned-20261114
```

For a different run, substitute its actual folder. The checker verifies retained
catalogue, manifest, CSV, document and context hashes/sizes and checks source URLs
in extracted context text. `integrity_ok` reports file integrity;
`harvest_complete` reports whether all required collection requests succeeded.
The command exits nonzero for either integrity errors or a partial harvest.
A partial download MUST NOT be described as fully complete scientific evidence.

## Tests

```text
uv run pytest
uv run ruff check .
uv run ruff format --check .
uv run python -m scripts.export_contracts --check
```

New tests use synthetic temporary fixtures and mock HTTP transports, never live
NASA requests or credentials. Coverage includes pagination, source filtering,
raw-byte retention, CSV encoding, signed-link resolution/expiry, retry/backoff,
cache corruption, version changes, strict size limits, selection/deduplication,
path safety, context extraction, offline replay, failure logs and checksum audits.

Local verification passed: **119 Python tests**, **10 web tests**, Python/web lint,
TypeScript checks, contract-drift checks and the production web build. The real
run's retained files also pass the SHA-256/size audit; `harvest_complete` remains
false because of the two recorded upstream PDF failures.

The Phase 2 API/UI fixtures remain unchanged. Downloading the corpus does not
populate the dashboard: reviewed normalization is Phase 4 and snapshot creation
is Phase 5.

## Complete-plan alignment follow-up

The supplied full plan now drives the canonical row contract, C/F/M/D weights,
rover/custom scenarios and exact context URLs. See `docs/context/PLAN_ALIGNMENT.md`.
Eight topics were captured; the two Apollo SMA URLs required explicitly logged
NASA article fallbacks. Three specified Spinoff URLs succeeded. The new run's
integrity audit verifies 118 source/text files. No normalization or real rankings
are claimed by these foundation changes.
