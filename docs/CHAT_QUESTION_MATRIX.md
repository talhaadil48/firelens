# Ten-question local chat test matrix

Tested sequentially against http://localhost:8001 using the exact supplied questions and investigation_ids.
Snapshot: 20261115-source-records-final; 2009 source records.

All ten requests returned HTTP 200 and an answer event. A supported label is evaluated independently here; it is not treated as proof of correctness.

| ID | Verdict | Actual response | Seconds |
| --- | --- | --- | ---: |
| A1 | FAIL + incorrect study assumption | supported; 0 test-row citations | 4.558 |
| A2 | FAIL: numeric constraint violated | supported; 3 row citations | 6.169 |
| A3 | CORRECT ABSTENTION / incorrect chart expectation | insufficient_evidence; no rows | 4.721 |
| A4 | FAIL: request semantics and chart mismatch | supported; 5 row citations | 6.18 |
| B1 | CORRECT ABSTENTION / source limitation | insufficient_evidence; no rows | 3.374 |
| B2 | CORRECT ABSTENTION / incorrect study assumption | insufficient_evidence; no rows | 49.97 |
| C1 | PARTIAL: relevant retrieval, incomplete explanation | supported; 4 text citations | 7.059 |
| C2 | PARTIAL: hypothesis retrieved, mechanism not explained | supported; 7 citations including 1 row | 5.335 |
| C3 | FAIL + incorrect study identity | supported; 5 citations including 1 row | 5.135 |
| D1 | PASS | insufficient_evidence; no citations | 4.412 |

## A1 ? FAIL + incorrect study assumption

Which PMMA or solid fuel test runs in PSI-69 were conducted above 20% oxygen, and what pressures and airflow rates were measured?

PSI-69 is FLEX: methanol/heptane droplets, no PMMA/solid rows and no airflow column. The answer should explain the mismatch/no matching runs; it instead marks general excerpts supported.

## A2 ? FAIL: numeric constraint violated

Which experimental test runs were performed at oxygen concentrations above 30% and pressures below 105 kPa? List specific test IDs and fuels.

A cited row inverse-21328D1 has o2_fraction=0.212319452 (21.23%), violating >30%. Parser fails to recognize oxygen concentrations above 30%. Snapshot contains 257 exact individual-row matches for O2>0.30 and pressure<105 kPa, across PSI-10/159/69. A scatter exists but includes an invalid match.

## A3 ? CORRECT ABSTENTION / incorrect chart expectation

What oxygen fractions and cabin pressures were measured across the test runs in PSI-101 and PSI-102?

PSI-101=SAME-R and PSI-102=SAME, not Saffire. Their imported tables have airflow, but no numeric oxygen+pressure pairs. No O2-pressure scatter can be justified. The response should identify the missing fields more specifically.

## A4 ? FAIL: request semantics and chart mismatch

What oxygen concentrations and pressures were tested in PSI-159 and PSI-107 ethylene or gaseous flame experiments?

The filter selects ethylene AND gas, not ethylene OR gaseous fuels. All cited rows are SPICE/PSI-107 airflow rows with null oxygen/pressure. The UI falls back to airflow bars despite a request for oxygen and pressure. PSI-159 has 333 coordinate pairs but no ethylene fuel labels; PSI-107 has no coordinate pairs.

## B1 ? CORRECT ABSTENTION / source limitation

Compare the airflow velocities (flow_cm_s) across cotton and PMMA test runs in PSI-25.

PSI-25=BASS-II. Its table has Flow restrictor, Fan display and Air display, not calibrated flow_cm_s values. All 129 normalized rows lack flow_cm_s. These settings cannot be relabelled cm/s without a calibration. Parser also picks cotton alone, losing the cotton/PMMA union.

## B2 ? CORRECT ABSTENTION / incorrect study assumption

What forced airflow velocities in cm/s were tested across the test runs in PSI-69?

PSI-69 is FLEX, not BASS. None of its 274 rows has a measured airflow column. No airflow bar chart should be fabricated. This request took about 50 seconds.

## C1 ? PARTIAL: relevant retrieval, incomplete explanation

What cool-flame behavior and droplet extinction phenomena were reported in the FLEX droplet combustion experiments?

Retrieves relevant CFI report passages discussing FLEX cool flames and extinction, plus FLEX-2 objectives. Evidence text contains prolonged cool-flame burning and composition-dependent behavior; the visible answer truncates passages and does not clearly synthesize the requested behavior. No row chart is expected.

## C2 ? PARTIAL: hypothesis retrieved, mechanism not explained

Why can solid materials in microgravity with low ventilation airflow burn more hazardously or at lower oxygen limits than in normal gravity according to PSI-25?

Retrieves the BASS-II hypothesis and relevant source metadata. The answer remains truncated excerpts, not a clear explanation of the mechanism and conditions. A hypothesis must not be represented as a demonstrated universal result.

## C3 ? FAIL + incorrect study identity

What were the main science objectives and soot findings of the Flame Design (PSI-159) investigation on the ISS?

Flame Design is PSI-10, whereas PSI-159 is CFI-G. The response fails to flag this contradiction and returns CFI-G operational/index passages and one row, rather than the requested objectives and soot findings.

## D1 ? PASS

Did NASA test lithium-ion battery thermal runaway at 80% oxygen and 300 kPa in a Martian dust storm?

Correctly refuses to invent the lithium-ion battery/Martian dust-storm experiment. This means no supporting evidence was retrieved in this snapshot; it does not prove NASA has never conducted such research.

## Source identity corrections

- PSI-69: FLEX; PSI-26: BASS; PSI-25: BASS-II.
- PSI-101: SAME-R; PSI-102: SAME. SAFFIRE-I/II/III are PSI-98/99/100.
- PSI-159: CFI-G; PSI-107: SPICE; PSI-10: Flame Design.
- FLEX is PSI-69 (FLEX-2 PSI-68), not PSI-20?23 (ACME investigations).

## Evidence and limits

Full answer text, citations, exact row values, progress frames and timings are retained in results.json. Source-export records are in source-records.json. Each question was run once; this is a reproducible single-run diagnosis, not a statistical accuracy estimate. Browser chart verification replays those exact recorded SSE answers against the real local table endpoints to avoid repeat model calls; chart-results.json records rendered types.

The requested multi-investigation frontend supports up to ten distinct IDs, removable chips, clear-all and default all-study scope. No API contract change was needed.

Remaining priority fixes: robust numeric parsing/strict comparisons; OR fuel filters; explicit no-match and wrong-study explanations; requested-chart field matching; complete relevant document excerpts rather than generic supported output. No backend filtering fix is claimed in this test-only follow-up.
