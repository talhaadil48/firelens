# Investigation review-label audit

Historical audit of the old snapshot. Review-status fields have since been removed; see [the replacement behavior](SOURCE_RECORDS_HANDOFF.md).

Audit date: 2026-11-15. Local evidence only; no new NASA downloads.

## Scope and conclusion

Audited all 24 investigations in snapshot `20261114T164500Z` (1,858 normalized rows), their mapping files, saved harvest report/manifests and original CSVs. All 22 downloaded experimental CSV hashes match the saved SHA-256 receipts.

The snapshot labels 9 investigations reviewed and 15 unreviewed. `harvest/precompute.py` assigns investigation status from the presence of normalized rows, not documented reviewer approval. `harvest/normalize.py` skips every `study_level_only` map; row status otherwise inherits the map flag. All 11 skipped table maps themselves say reviewed. Therefore investigation and mapping review labels do not describe the same event.

None of the 15 unreviewed investigations has a failed table download in this saved harvest: 11 have successfully downloaded tables intentionally skipped by normalization; four have no experimental table listed in the saved manifest. These findings do not establish the absence of relevant data in publications, reports or uncollected files.

A reviewed label alone is not proof of a completed human science review. This audit verifies processing/status assignment and retained source files; it is not scientific validation.

## Every investigation

| Investigation | Snapshot label | Normalized rows | Verified reason |
| --- | --- | ---: | --- |
| PSI-10 ? ACME/Flame Design | reviewed | 327 | Per-test table mapping produced rows, so precompute automatically sets the investigation to reviewed. This does not establish documented independent human approval. |
| PSI-100 ? SAFFIRE-III | unreviewed | 0 | Downloaded two sample entries with material, dimensions, airflow and direction. The map skips the entire table because oxygen/pressure columns are absent. Import limitation: missing oxygen/pressure alone does not prevent importing other reported fields with nulls. |
| PSI-101 ? SAME-R | reviewed | 109 | Per-test table mapping produced rows, so precompute automatically sets the investigation to reviewed. This does not establish documented independent human approval. |
| PSI-102 ? SAME | reviewed | 8 | Per-test table mapping produced rows, so precompute automatically sets the investigation to reviewed. This does not establish documented independent human approval. |
| PSI-106 ? SLICE | unreviewed | 0 | Downloaded 12 daily campaign entries with dates and fuel/narrative descriptions. These are not individual flame tests; the map keeps the table at study level. |
| PSI-107 ? SPICE | reviewed | 469 | Per-test table mapping produced rows, so precompute automatically sets the investigation to reviewed. This does not establish documented independent human approval. |
| PSI-115 ? Utilization of the Smoke Aerosol Measurement Experiment Data for Advanced Modeling and Simulation of Smoke Generation in Micro-Gravity | unreviewed | 0 | Saved NASA manifest has experimentalTable=[] and assays=[]; harvest contains reports/science documents, no experimental CSV. No table mapping exists. This does not establish that measurements are absent from the documents. |
| PSI-117 ? Effect of External Thermo-Convective Perturbation on Cool Flame Dynamics: A Multidimensional Multi-Physics CFD Analysis | unreviewed | 0 | Saved NASA manifest has experimentalTable=[] and assays=[]; harvest contains a report, no experimental CSV. No table mapping exists. This does not establish that numerical simulation results are absent from the report. |
| PSI-142 ? Quantitative Studies of Cool Flame Transitions at Radiation / Stretch Extinction Using Counterflow Flames | unreviewed | 0 | Downloaded eight references to data descriptions/publication figures. Columns identify publications and figure numbers, not individual numerical test conditions. Map keeps the index at study level. |
| PSI-159 ? ACME CFI-G | reviewed | 333 | Per-test table mapping produced rows, so precompute automatically sets the investigation to reviewed. This does not establish documented independent human approval. |
| PSI-20 ? ACME BRE | unreviewed | 0 | Downloaded 18 daily summaries. Oxygen cells contain lists such as 21; 26.5; 40; notes say chamber pressures varied but are not identified. Daily flame counts do not identify each flame's conditions. Map skips these study-level records. |
| PSI-21 ? ACME CLD Flame | unreviewed | 0 | Downloaded 32 campaign summaries. Fuel concentration cells give ranges such as 30%-40%, with daily flame counts; source notes say concentrations varied between and sometimes during tests. No exact per-flame pairing. Map keeps the table at study level. |
| PSI-22 ? ACME E-FIELD Flames | unreviewed | 0 | Downloaded 32 daily/grouped entries with polarity, fuel and flame counts. Each daily entry can describe multiple flames. Map does not expand these groups into individual tests. |
| PSI-23 ? ACME s-Flame | unreviewed | 0 | Downloaded 18 grouped entries with approximate atmosphere strings and daily flame counts. Source notes say oxygen drops and pressure rises as the atmosphere changes. Map does not assign a precise condition to each flame. |
| PSI-25 ? BASS-II | reviewed | 129 | Per-test table mapping produced rows, so precompute automatically sets the investigation to reviewed. This does not establish documented independent human approval. |
| PSI-26 ? BASS | reviewed | 122 | Per-test table mapping produced rows, so precompute automatically sets the investigation to reviewed. This does not establish documented independent human approval. |
| PSI-39 ? CFI | reviewed | 87 | Per-test table mapping produced rows, so precompute automatically sets the investigation to reviewed. This does not establish documented independent human approval. |
| PSI-47 ? DAFT / DAFT-2 | unreviewed | 0 | Downloaded two aerosol measurement session descriptions (hardware, sample, location and day), without numerical measured outputs in this table. Map keeps these descriptive sessions at study level. |
| PSI-60 ? Computational and Experimental Analysis of SPICE Data Sets | unreviewed | 0 | Saved NASA manifest has experimentalTable=[] and assays=[]; no downloadable table/report was collected for this record. No table mapping exists. Metadata/publications may still lead to evidence outside the collected files. |
| PSI-62 ? Concurrent Flame Spread Modeling using Flamelet Generated Manifolds in Microgravity with Comparison to BASS Experiments using Two-Color Tomography | unreviewed | 0 | Saved NASA manifest has experimentalTable=[] and assays=[]; no downloadable table/report was collected for this record. No table mapping exists. Metadata/publications may still lead to evidence outside the collected files. |
| PSI-68 ? FLEX-2 | unreviewed | 0 | Downloaded eight fuel-summary entries. Diameter/flow are ranges and oxygen/pressure are lists. Source does not pair each oxygen, pressure and diameter with an individual test. Map deliberately does not invent combinations. |
| PSI-69 ? FLEX | reviewed | 274 | Per-test table mapping produced rows, so precompute automatically sets the investigation to reviewed. This does not establish documented independent human approval. |
| PSI-98 ? SAFFIRE-I | unreviewed | 0 | Downloaded four entries containing sample measurements, oxygen ranges/approximations and pre-test visualization entries. Map currently skips the entire table. Import limitation: useful sample measurements could be retained with explicit range/approximation handling and exclusion of non-test entries. |
| PSI-99 ? SAFFIRE-II | unreviewed | 0 | Downloaded 15 entries containing material/sample measurements, approximate oxygen, units inside cells and qualitative outcomes. Map currently skips the entire table. Import limitation: requires unit parsing, uncertainty handling and separation of quantitative/qualitative fields, rather than discarding all entries. |

## Evidence and reproducibility

- Active pointer: `snapshots/latest.json`.
- Snapshot records: `snapshots/20261114T164500Z/investigations.json`.
- Original collection: `raw/plan-aligned-20261114/`; report: `raw/plan-aligned-20261114/report.json`. Original files remain ignored.
- Saved manifests: `raw/plan-aligned-20261114/PSI-<id>/manifest.json`.
- Mapping decisions: `harvest/maps/PSI-<id>.yaml`.
- Status assignment: `harvest/precompute.py`, `build_investigations`; skip behavior: `harvest/normalize.py`, `normalize_all`.
- Human mapping-check policy: `harvest/maps/README.md`; limitation already acknowledged in `docs/context/PHASE_6_REVIEW.md`.

### Verified original table SHA-256 hashes

| Accession | Original filename | SHA-256 |
| --- | --- | --- |
| PSI-10 | PSI-10_Experimental table_Flame Design_Normal Flame.csv | `4a663292bd3f65201943cc71bd661a70383639276a9176f64105b285bf0b6deb` |
| PSI-10 | PSI-10_Experimental table_Flame Design_Inverse Flame.csv | `97933ee9ae0b9ebc6b948a67485a0fe2f8218f753253a4f2be93c40d374c44e4` |
| PSI-20 | PSI-20_Experimental table_ACME BRE.csv | `4aa5d3f98708ceacced5c620d46858b9965f8d4d941b203229f46467d53e5ab7` |
| PSI-21 | PSI-21_Experimental table_CLD Flame.csv | `9fafbc5b3dddaf715ce8025ed9154ce297803f7b69a935f077ec26c8249e44c0` |
| PSI-22 | PSI-22_Experimental table_ACME E-FIELD Flames.csv | `69090c357b83ae38d161d29001d1d32b40fd77b13324ca6585ee990cdceef524` |
| PSI-23 | PSI-23_Experimental table_ACME s-Flame.csv | `16cd10f50bd2e962887c8eb4077e5a9b3e790c78de8e0361c0b77e19300be7cf` |
| PSI-25 | PSI-25_Experimental table_BASS-II.csv | `71e792bf6b5fb5ea620c5dd70fbbac05515992e12aefcf5dff47312caa48c042` |
| PSI-26 | PSI-26_Experimental table_BASS.csv | `ccfc3c54d948b64a1c5d2596a63c7c8019e51df0c91a1d62f039f48fa28c300f` |
| PSI-39 | PSI-39_Experimental table_CFI.csv | `fb898e28762353aa132c16b886dbd207a024b1dd3c9bed5928d70d8036d2ec7e` |
| PSI-47 | PSI-47_Experimental table_DAFT.csv | `d9d1a436c6e7bbc410b433e04575fe7dedaff763b5237d688089929b7393b5c0` |
| PSI-68 | PSI-68_Experimental table_Flex2.csv | `cc57ad1bd9977aa13e7ac6c3aa618303012686e232b36c052c6a9f1a74e5f528` |
| PSI-69 | PSI-69_Experimental table_FLEX.csv | `37c88ce8ae9391b7544ff630a45ce87543d04d317cdbfbed104fe7d5c27e1b96` |
| PSI-98 | PSI-98_Experimental table_SAFFIRE-1.csv | `c01f29c62455f0a3b512290ab85e5687ecded326733189f002f580368402308d` |
| PSI-99 | PSI-99_Experimental table_SAFFIRE-2.csv | `3c24390b9ef86f3d1ebaab911a1a3cc95a8759aebf42062371370e6d4b31b8ac` |
| PSI-100 | PSI-100_Experimental table_SAFFIRE-3.csv | `4d3c717ec20dd0247db670b2784a9fd7d746788bc54a936f80693e48eb8cd117` |
| PSI-101 | PSI-101_Experimental table_SAME-R.csv | `87164b7dc9168a4273c159f7a9f23699afbd06ad97b77974377e79b9bf8a3bef` |
| PSI-102 | PSI-102_Experimental table_SAME.csv | `268d1e121d2f211b124407dd32b9475617bd269ede2c2d1749441da3e949a2af` |
| PSI-106 | PSI-106_Experimental table_Slice.csv | `89ef980810ca6d9aa8be817b42e36cd2adff23f5e9058361b5a33d18b4363f4d` |
| PSI-107 | PSI-107_Experimental table_Spice.csv | `fb0d7e60cf5367afb429089e9901d27288f78038efd26c8de1db4fbe04117136` |
| PSI-142 | PSI-142_Experimental table_Data Summary Table.csv | `c66d135b0053590d239f06b9e8627d826e3d726b8443fd2cbccc37484b6a8e7f` |
| PSI-159 | PSI-159_Experimental table_CFI-G_Normal Flames.csv | `d95a621c3fbd27d204dd32ed29fa17d68f2b779d6a523cde8479ed7ebaa5251a` |
| PSI-159 | PSI-159_Experimental table_CFI-G_Inverse Flames.csv | `d4d44f8b9896936728748e34d1b6ad0812032a92fa5289599b708c138e3a9b39` |
