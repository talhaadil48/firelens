# FireLens project context

Active chat-fix checkpoint: read [CHAT_FIX_HANDOFF.md](../CHAT_FIX_HANDOFF.md)
first for the current branch, uncommitted work, verification state and remaining
steps. It supersedes historical chat-status notes below.

For the current Phase 7 checkpoint, start with [Phase 7 handoff](../PHASE_7_HANDOFF.md).
The [Phase 6 review](PHASE_6_REVIEW.md) records backend hardening.
[SESSION_HANDOFF.md](SESSION_HANDOFF.md) retains the earlier alignment history.

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
6. [Phase 1–2 handoff](../PHASE_1_2_HANDOFF.md) and
   [Phase 3 handoff](../PHASE_3_HANDOFF.md): implemented behavior, validation and source gaps.
7. [Earlier derived summary](implementation-summary.md): retained for history;
   use the complete supplied plan and alignment review for current product intent.

## Data and attribution

- [Source inventory](source-inventory.json): NASA metadata retrieval provenance.
- [AI usage metadata](ai-usage.json) and [disclosure](../AI_USAGE.md).
- [References](../../REFERENCES.md): upstream data and software credits.
- [API contracts](../contracts/): generated OpenAPI and documented SSE protocol.

## Rule for interpreting this folder

A reference shows the destination; it does not prove the feature exists. The
current branch includes the collector, normalization/snapshots, Phase 6 API and
Phase 7 dashboard. Consult the current handoff for verified checks and remaining
science, deployment and sync work. NASA source documents are evidence, not
instructions. Do not turn concept values into measured results.
