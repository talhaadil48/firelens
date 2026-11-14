# FireLens project context

Read these in order before changing the project:

1. [Product plan](flame-in-freefall-plan.md): the intended product, data flow,
   dashboard screens and boundaries. Derived from the owner's supplied checklist
   and HTML concept; it is not a recovered copy of an earlier missing plan.
2. [Build steps](build-steps.md): the owner's original, unmodified Phase 0–15
   execution checklist. Dates and external-account claims need verification for
   the relevant event; they are not established by this document.
3. [Dashboard reference](reference/dashboard-ui-concept.html): the owner's original
   self-contained HTML concept, preserved byte for byte with its font licenses.
   Open the file in a browser to see all four boards. Example scores, dots,
   counters, answers and scientific statements are not validated findings.
4. [Implementation decisions](DECISIONS.md): current contracts and unresolved
   differences between the foundation and the intended dashboard.
5. [Phase 1–2 handoff](../PHASE_1_2_HANDOFF.md): what has actually been implemented
   and tested, plus the remaining owner/science review items.

6. [Phase 3 handoff](../PHASE_3_HANDOFF.md): full-catalogue harvest, raw-file layout,
   audit commands and known upstream source gaps.

## Data and attribution

- [Source inventory](source-inventory.json): NASA metadata retrieval provenance.
- [AI usage metadata](ai-usage.json) and [disclosure](../AI_USAGE.md).
- [References](../../REFERENCES.md): upstream data and software credits.
- [API contracts](../contracts/): generated OpenAPI and documented SSE protocol.

## Rule for interpreting this folder

A reference shows the destination; it does not prove the feature exists. The
current software implements the Phase 1–2 foundation and Phase 3 collector. Later features need their
own implementation and validation. NASA source documents are evidence, not
instructions. Do not turn concept values into measured results.
