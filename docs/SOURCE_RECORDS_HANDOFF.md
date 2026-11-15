# Source records, missing data and review-label removal

The owner explicitly requested preserving all available dataset fields and removing
the reviewed/unreviewed system. This supersedes earlier review-flag instructions
and the status logic documented in the historical handoffs/audit.

## Current behavior

- Every nonblank CSV source row and every original cell is retained. Original
  headers, column positions, strings, units, ranges, lists and qualitative values
  travel with the row as `source_cells`. Physical row numbers, file/version/URL,
  retrieval timestamps and actual source SHA-256 hashes remain attached.
- A missing or non-scalar field leaves just that standardized field null; it does
  not discard other source fields or the row. Notes explain parsing limitations.
- All 22 downloaded tables are imported: 2,009 source records, including 151 records
  previously skipped. Raw files are unchanged and remain ignored.
- Grouped summaries, sessions, references and source notes are identified by
  `record_kind`. They never become invented independent tests or condition pairs.
  An unmapped CSV is retained as source cells with no guessed scalar mappings.
- `Investigation.record_count` counts all imported records. `test_count` counts
  individual-test records. The legacy snapshot/meta `test_count` and `/tests`
  pagination total count source records; the web labels those totals accordingly.
- No review-status enum, fields, configuration flags, filters, gates, badges or
  export options remain. Eligibility for numeric charts/ranking/chat depends on
  individual measurement evidence, available numbers and source provenance.
  Simulation and mock rows remain distinguishable and cannot become measurements.
- Measurements loads every API page, provides original-column and standardized
  views, switches between source files and paginates at 50 rows. All standardized
  fields, named metrics and provenance remain inspectable. Exports preserve original
  cells and fields; CSV includes provenance JSON and record kind.
- Investigation pages show collection/extraction limitations on opening, including
  missing exact scalar conditions and missing instrumentation extraction. The four
  studies without collected tables retain their metadata/documents/publications;
  the disclaimer does not claim their research lacks measurements.

## Regenerate existing local snapshots

Old snapshots contain removed fields and must be rebuilt before running this API.
No environment variable changes, cloud provisioning or downloads are needed when
this retained raw collection exists:

```text
uv run python -m harvest.pipeline all --raw-dir raw/plan-aligned-20261114 --snapshot-id source-records-v2
```

Restart the backend after rebuilding. Existing snapshots are retained; only the
local latest pointer selects the new one. Do not serve an old image/API against
this new contract. The shared Python models, OpenAPI, sample fixtures and generated
TypeScript must move together.

## Validation

- Python: 153 tests, Ruff lint/format and contract drift check.
- Web: 27 tests, ESLint, TypeScript and production build.
- A local real-data test checks every nonblank row/cell from all 22 original CSVs
  against imported records and verifies their full SHA-256 hashes.
- Added coverage for partial records, grouped values, unmapped files, original
  multi-line cells and physical row locations, retained source notes, pagination,
  multiple source tables and original-column rendering.
- Browser checks against the real snapshot cover eight investigation pages,
  partially populated SAFFIRE-III, FLEX-2 ranges, FLEX pagination, both CFI-G files,
  missing-data notices, absence of review labels and 393px layouts. Export JSON
  contains all 2,009 records with original cells and hashes. Screenshots are in
  ignored `artifacts/phase7/measurements-*.png`.

No scientific validation, safety certification or deployment is claimed. Existing
Plotly bundle-size and Starlette/httpx deprecation advisories remain.
