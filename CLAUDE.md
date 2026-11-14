# FireLens working instructions

Read `AGENTS.md` and `docs/context/README.md` first. Then read the product plan,
original build checklist, dashboard reference and recorded decisions linked there.
Shared science/API models live in `api/models.py`. Run `make contracts` and regenerate
web types after any contract change. Never call external LLMs or NASA from CI tests.
