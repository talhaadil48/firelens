> Historical Phase 1–3 assessment. The later phases have since been implemented;
> read the code and its verified checks for current behaviour.

# Supplied plan alignment — Phase 1–3 foundation

Updated 14 November 2026 after the owner authorized fixing the differences found
in the original review. The complete supplied plan remains unchanged in
`flame-in-freefall-plan.md`. This file records the state at that point.

## Aligned in this update

| Requirement | Current implementation |
| --- | --- |
| Complete normalized-row contract | `ExperimentalTest` now has investigation/date, fuel/phase, sample geometry/size/dimensions, oxygen/basis, pressure, diluent/composition, flow/direction, controlled outcome, multiple named metrics, DOI and source references. This defines the format; it does not normalize the raw CSVs. |
| Existing consumers | Legacy `material`, `geometry` and `oxygen_fraction` input aliases remain accepted; JSON uses `fuel`, `sample_geometry`, `o2_fraction`. Legacy single-value outcomes remain optional. Flat source fields must agree with nested provenance. |
| Table validation | Pandera validates canonical columns and retains all Pydantic-validated metrics/evidence fields instead of discarding them. Missing values remain null. |
| Investigation metadata | Models and real-metadata fixtures expose objective/approach/hypothesis/impacts, sub-area, DOI, hardware/platform, publications and aggregate file counts/sizes. Sensors and AI summaries remain unknown until supported extraction/review. |
| Ranking definitions | Weights now mean conditions 0.40, fuel realism 0.25, safety goal 0.20, data richness 0.15. Real scores remain null until reviewed data/ranking implementation exists. |
| Mission profiles | Earth/ISS use the supplied 14.7 psi scenario, Moon/rover use >=30% oxygen and <=10.2 psi, suit uses 100% oxygen at 4.3 psi. Values convert to kPa. Unspecified airflow/gravity remains unknown; these are scenarios, not certified requirements. |
| Custom conditions | Sixth `custom` profile, API validation and a web form for oxygen, pressure, optional flow/gravity. Canonical `o2_fraction` and the deprecated query alias are handled consistently. Safety goal is explicit in the rank contract. |
| Exact source list | Configuration now includes the plan's Apollo SMA URLs, Mir, all three specified Spinoffs (9582, 9407, 9918), combustion page and requested Guide URL. Fallbacks are explicit and logged. |
| Generated artifacts | OpenAPI, TypeScript declarations and fixtures are regenerated together. API compatibility and custom-input tests cover the changed contracts. |

## What the real collection contains

Latest run: `raw/plan-aligned-20261114/`; audit/report files are under `docs/harvest/`.
There are 24 manifests, 22 experimental CSVs, 53 supporting documents and eight
captured context topics. The audit verifies 118 original-source/extracted-text
files. Raw data/cache stays local and ignored by Git.

The source-gap status remains honest:

- Two legacy PSI-26 final-report entries return 404, so collection stays partial.
- Both exact Apollo SMA URLs were attempted but required the explicitly recorded
  NASA article fallbacks. `requested_url`, actual URL and attempt history are saved.
- All three exact Spinoff pages and the requested Researcher's Guide URL succeeded.
- Official challenge-page capture remains unavailable in this environment.
- Four investigations have no experimental table. No rows or reports were fabricated.

## Later phases remain later phases

This update aligns the existing foundation with the supplied plan. It does not
claim Phase 4 normalization/maps, reviewed summaries, general report/DOCX chunking,
embeddings, DuckDB/Parquet storage, actual relevance scores, grounded model calls,
the final four-screen UI, real normalized-data exports, related-study similarity,
cloud hosting, live freshness or nightly synchronization are implemented.

The API still serves clearly labelled mock responses. The custom form applies
conditions but does not pretend a safety score or scientific result exists.
Numbers must eventually come from reviewed code/data and claims from evidence.

## Continuing safely

- Implement actual normalization against this canonical schema; preserve dates,
  units, ranges, sample geometry, multiple metrics and per-test versus study-wide facts.
- Use C/F/M/D when implementing ranking; define component tolerances and missing-data
  behavior and validate relevance separately from physical safety.
- Keep originals as ingestion inputs and cite upstream PSI/DOI links to users.
- Do not treat the plan's historical inventory counts, prices, offers, mission-status
  statements or event dates/rules as independently verified current facts.
- Do not add operational predictions or invented partial-gravity measurements.
