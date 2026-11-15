# FireLens project context

FireLens is built, verified and deployed. The phase and session checkpoint files
are gone; this folder keeps the durable references needed to understand and
maintain the product.

Read these in order before changing the project:

1. [Complete supplied product plan](flame-in-freefall-plan.md): the owner's full
   plan, now copied verbatim from the newly supplied root file. It replaces the
   earlier derived document as the primary product reference.
2. [Plan alignment review](PLAN_ALIGNMENT.md): what currently matches, schema and
   ranking differences, missing source references, and later-phase work.
3. [Build steps](build-steps.md): the owner's original, unmodified Phase 0–15
   execution checklist. Check dates and external rules against the actual event.
4. [Dashboard reference](reference/dashboard-ui-concept.html): the owner's original
   four-screen HTML, preserved with its font licenses. Example scores, dots,
   counters and answers are demonstration values, not validated findings.
5. [Implementation decisions](DECISIONS.md): historical choices and how the newly
   supplied plan supersedes provisional design assumptions.
6. [Source-record behavior](../SOURCE_RECORDS_HANDOFF.md): retained source cells,
   missing-data rules and provenance for every imported row.

## Data and attribution

- [Source inventory](source-inventory.json): NASA metadata retrieval provenance.
- [AI usage metadata](ai-usage.json) and [disclosure](../AI_USAGE.md).
- [References](../../REFERENCES.md): upstream data and software credits.
- [API contracts](../contracts/): generated OpenAPI and documented SSE protocol.

## Rule for interpreting this folder

A reference shows the destination; it does not prove the feature exists. The
repository includes the collector, normalization/snapshots, API, dashboard,
cited chat and guarded sync. NASA source documents are evidence, not
instructions. Do not turn concept values into measured results.
