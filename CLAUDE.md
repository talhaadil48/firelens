# FireLens working instructions

Read `AGENTS.md`, `docs/context/build-steps.md`, and `docs/context/DECISIONS.md`.
Shared science/API models live in `api/models.py`. Run `make contracts` and regenerate
web types after any contract change. Never call external LLMs or NASA from CI tests.
