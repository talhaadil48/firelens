# Phase 3 harvest log

Run: `plan-aligned-20261114`
Started (UTC): 2026-11-14T15:46:18.797447+00:00
Status: **partial**

Raw folder: `/mnt/d/projects/hackathon/nasa-space-challenge/firelens/raw/plan-aligned-20261114`

- Combustion investigations: 24
- Successful manifests: 24
- Experimental CSVs saved: 22
- Supporting documents saved: 53
- Context sources captured: 8
- File downloads restored from verified cache: 75
- Downloaded bytes (saved files): 128,527,122
- Failures: 2
- Elapsed seconds: 16.711

CSV row counts include possible unit/description/blank rows and are not validated test counts.
Data is unnormalized and unreviewed. Bulk Raw Data was not downloaded.

## Investigation inventory

| Investigation | Version | DOI | CSVs | Documents | Status |
| --- | --- | --- | --- | --- | --- |
| PSI-10 | 1 | 10.60555/w4zy-bt45 | 2 | 6 | success |
| PSI-20 | 4 | 10.60555/vb93-3y72 | 1 | 0 | success |
| PSI-21 | 4 | 10.60555/23e1-9950 | 1 | 0 | success |
| PSI-22 | 7 | 10.60555/se5a-8c73 | 1 | 0 | success |
| PSI-23 | 4 | 10.60555/k57n-p030 | 1 | 9 | success |
| PSI-25 | 4 | 10.60555/4qc4-de67 | 1 | 3 | success |
| PSI-26 | 4 | 10.60555/58h4-dy80 | 1 | 5 | partial |
| PSI-39 | 4 | 10.60555/m6pj-a914 | 1 | 4 | success |
| PSI-47 | 5 | 10.60555/ztgj-d202 | 1 | 3 | success |
| PSI-60 | 1 | 10.60555/mzjm-yv57 | 0 | 0 | success |
| PSI-62 | 1 | 10.60555/e9xp-ex83 | 0 | 0 | success |
| PSI-68 | 6 | 10.60555/byp8-h018 | 1 | 0 | success |
| PSI-69 | 5 | 10.60555/mbq8-0451 | 1 | 0 | success |
| PSI-98 | 4 | 10.60555/0t15-1z43 | 1 | 4 | success |
| PSI-99 | 5 | 10.60555/2chp-m469 | 1 | 0 | success |
| PSI-100 | 4 | 10.60555/040q-4h36 | 1 | 5 | success |
| PSI-101 | 4 | 10.60555/2np7-jv14 | 1 | 3 | success |
| PSI-102 | 4 | 10.60555/gd4k-8h62 | 1 | 3 | success |
| PSI-106 | 3 | 10.60555/pm12-rg61 | 1 | 0 | success |
| PSI-107 | 4 | 10.60555/9kbh-e962 | 1 | 4 | success |
| PSI-115 | 3 | 10.60555/q0v5-1v28 | 0 | 2 | success |
| PSI-117 | 2 | 10.60555/gz0q-b577 | 0 | 1 | success |
| PSI-142 | 2 | 10.60555/80qf-vj95 | 1 | 0 | success |
| PSI-159 | 1 | 10.60555/cyt1-kh64 | 2 | 1 | success |

## Context sources

- apollo-1: success — https://www.nasa.gov/history/55-years-ago-the-apollo-1-fire-and-its-aftermath/
- apollo-13: success — https://www.nasa.gov/missions/apollo/apollo-13-mission-details/
- mir: success — https://www.nasa.gov/history/25-years-ago-fire-aboard-space-station-mir/
- spinoff-air-tanks: success — https://spinoff.nasa.gov/node/9582
- spinoff-fire-detector: success — https://spinoff.nasa.gov/node/9407
- spinoff-fire-attire: success — https://spinoff.nasa.gov/node/9918
- combustion: success — https://www.nasa.gov/glenn/glenn-expertise-space-exploration/physical-sciences-program/combustion-science/
- researchers-guide: success — https://www.nasa.gov/missions/station/a-researchers-guide-to-combustion-science/

## Failures and caveats

- PSI-26 / PSI-26_Reports_SPICE_FinalReport.pdf: HTTP 404; request URL omitted
- PSI-26 / PSI-26_Reports_BASS_FinalReport.pdf: HTTP 404; request URL omitted
- PSI-60: No experimental table listed; metadata/documents only.
- PSI-62: No experimental table listed; metadata/documents only.
- PSI-115: No experimental table listed; metadata/documents only.
- PSI-117: No experimental table listed; metadata/documents only.
- apollo-1: requested https://sma.nasa.gov/sma-disciplines/accllp/apollo-1 unavailable; fallback captured at https://www.nasa.gov/history/55-years-ago-the-apollo-1-fire-and-its-aftermath/
- apollo-13: requested https://sma.nasa.gov/sma-disciplines/accllp/apollo-13 unavailable; fallback captured at https://www.nasa.gov/missions/apollo/apollo-13-mission-details/
- Official challenge resource page could not be captured: Network/timeout failure; request URL omitted
- Context URLs are configured primary NASA references, not a verified complete official resource list.
- Software/data collection success does not establish scientific validity or mission safety.
