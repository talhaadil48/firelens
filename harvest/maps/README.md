# Phase 4 Column Maps

Each experimental CSV normalized in Phase 4 gets a reviewed YAML file here
named `PSI-<n>.yaml` (or `PSI-<n>_<table-slug>.yaml` when an investigation has
multiple CSVs, such as `PSI-159` normal/inverse flames).

All YAML files must validate against `harvest.maps_schema.ColumnMap`.

## Rules
- Never fabricate independent test rows from range strings (`"1.5 - 5"`) or
  delimited multi-value cells (`"21; 26.5; 40"`). Use `range_policy` or
  `study_level_only: true` when a table cannot be mapped cleanly row-by-row.
- Keep `review_status: unreviewed` until a teammate has checked the exact CSV
  headers, units, and conversions against the raw file.
