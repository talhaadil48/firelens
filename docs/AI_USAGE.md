# How AI was used

FireLens uses AI in two places: inside the product, to write explanations, and as a coding
assistant while we built it. In both, people set the rules and checked the results, and the
science comes from NASA's data, not from a model.

## In the product

**What the model does.** FireLens calls one language model, `openai/gpt-4o-mini` through
OpenRouter, for two jobs:

- writing plain-language summaries of investigations, and
- answering questions on the **Ask FireLens** screen.

**What the model never does.**

- **It never produces numbers.** Rankings, ranges, counts, coverage maps and the charts
  inside answers are computed with SQL over the harvested NASA data. The model only
  receives these computed facts and the retrieved report passages, and puts them into
  words.
- **It never answers without sources.** Every answer cites its sources (PSI accession,
  DOI, file, and page or row). Cited passage IDs and text are checked against the
  retrieved evidence before an answer is shown; if the check fails, FireLens shows a
  plain evidence summary instead. If nothing relevant is retrieved, it says so.
- **It never fills gaps.** A value that isn't in the data stays empty. No measurement,
  partial-gravity result or safety rating is generated.

**Retrieval needs no model.** Search over report text uses a deterministic local
embedding. Measurement rows are queried with SQL, never with embeddings.

**Keys stay on the server.** The model and its key live only in the backend's
environment. Automated tests never call a model or NASA; they use an offline mode and
test doubles.

## In building it

**The assistants.** Two AI coding assistants worked on the repository, each directed by a
team member:

- **OpenAI Codex**, directed by Talha Adil:
  - the data harvester, normalization and snapshot pipeline;
  - the API, including ranking and the cited chat;
  - the React dashboard;
  - tests and documentation through the dashboard phase.
- **Claude Code (Claude Opus)**, directed by Muhammad Qambar Hussain:
  - Azure provisioning;
  - GitHub Actions deployment, including the guarded deploy with automatic rollback;
  - the nightly sync job;
  - the snapshot checker;
  - this documentation pass.

  Its commits carry a `Co-Authored-By: Claude` line in the Git history.

**How we kept control.**

- **Rules written down first.** The rules above, along with unit conventions and "never
  invent values", were set in the project instructions before any code was written, and
  the assistants worked within them.
- **Every change was reviewed and tested before merging.** CI runs linting, the test
  suites, contract-drift checks and a production web build on each pull request.
- **Deployment changes were rehearsed.** They were tried on a private staging copy first,
  including a deliberate failure to prove the automatic rollback works.
- **Data claims were checked against the source.** Record counts, DOIs and links were
  compared with the harvested PSI files and the live PSI pages.

## Limits

- **Not reviewed by a combustion scientist.** Passing software tests is not scientific
  validation.
- **The mission profiles and ranking weights are our assumptions**, not NASA
  specifications.
- **No AI-generated images, audio or video are used**, and no NASA branding.
