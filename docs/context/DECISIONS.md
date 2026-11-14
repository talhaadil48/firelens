# Phase 1–2 decisions and unresolved review items

1. Only the build checklist was supplied. The referenced `flame-in-freefall-plan.md`
   and original `CLAUDE.md` were not supplied. This repository records a provisional,
   explicit schema instead of pretending the missing pipeline specification was read.
2. FLEX has one experimental CSV; CFI-G has two (normal/inverse flames). Download
   all three. FLEX needs cp1252 decoding; retain original bytes and record encoding.
3. Five metadata fixtures come from public PSI manifests. Findings only repeat the
   catalogue title with its source field; there are no made-up physical conclusions.
   The empty tests response is intentional until Phase 4 normalization.
4. Frozen contract routes use `/investigations/{accession}` (the same identifier as
   the plan's `{id}`). `/profiles` is an additional typed route for shared UI config.
5. Assign weights 0.40/0.25/0.20/0.15 to oxygen/pressure/flow/gravity respectively.
   The supplied checklist gave weights but not dimension definitions. This is a
   provisional design choice requiring human/science approval before real ranking.
6. Earth/ISS use rounded illustrative values. Moon-base and spacesuit use the
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

## Added context after the UI reference was supplied

The supplied HTML concept is preserved at `reference/dashboard-ui-concept.html`.
A derived product plan is now available as `flame-in-freefall-plan.md`; it is not
the previously missing original detailed plan mentioned in decision 1.

The HTML clarifies an intended alternative scoring formula: conditions match
(0.40), fuel realism (0.25), safety goal (0.20), data richness (0.15). This differs
from the provisional dimensions in decision 5 and `config/profiles.yaml`. A coordinated contract/config update and scientific validation are needed before
real ranking; use the active task instructions to resolve the design. The reference also supplies additional rover/airflow assumptions and
uses `moon`/`suit` IDs; see the product plan for the differences. No runtime
configuration or scientific result was changed by this documentation update.

## Phase 3 collection

The owner authorized Phase 3 on `feature/phase-3-harvest`, based on current main.
The collector paginates the complete catalogue before filtering Combustion Science;
it does not assume the checklist's approximate investigation count. Current results
contain 24 manifests and 22 experimental CSVs. It excludes bulk Raw Data and keeps
raw collection separate from the unchanged Phase 2 API/UI fixtures. See the Phase 3
handoff and harvest log for the two unresolved upstream PDF links.

## Complete product plan received

The owner has now supplied the original complete `flame-in-freefall-plan.md`.
It is preserved verbatim under that name in this context directory. The previous
derived plan is retained as `implementation-summary.md`. Read `PLAN_ALIGNMENT.md`
for the code-level comparison.

The supplied plan establishes C/F/M/D (conditions, fuel realism, safety goal, data
richness) as the intended ranking design, superseding decision 5's provisional
dimensions. It also provides a fuller normalized row schema, rover/custom profile
requirements and three exact Spinoff sources. Runtime models/configuration remain
unchanged in this documentation task; those differences must be addressed during
the corresponding authorized implementation work.

## Implemented complete-plan alignment

The owner authorized alignment on the current branch. The canonical row schema,
C/F/M/D weights, profile/custom contracts and exact context source configuration
now follow the full plan. Legacy row/query aliases preserve compatibility. The
new collection uses `raw/plan-aligned-20261114/` (eight context topics, documented
Apollo fallbacks, two missing PDFs). See `PLAN_ALIGNMENT.md` and the active
`SESSION_HANDOFF.md`; prior provisional decisions are historical. No live scientific
ranking, normalization or deployment was added by this foundation update.
