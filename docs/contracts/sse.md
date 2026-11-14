# API contract and SSE protocol

`openapi.json` is generated from `api/models.py` and `api/main.py`.
Phase 2 serves offline mock responses. No production inference is implemented.

| Method | Route | Result |
| --- | --- | --- |
| GET | `/meta` | Snapshot identity, counts, nullable freshness check, warnings |
| GET | `/profiles` | Shared illustrative profiles and draft weights |
| GET | `/investigations?q=&limit=100&offset=0` | Filtered/paginated list |
| GET | `/investigations/{accession}` | Record, source links and citations |
| GET | `/rank?profile=iss` | Null scores with gap explanations; optional `oxygen_fraction`, `pressure_kpa`, `flow_cm_s` overrides |
| GET | `/tests` | Empty list until normalized data exists; accession/oxygen/pressure filters accepted |
| GET | `/compare?ids=PSI-26,PSI-25` | 2–3 distinct records and metadata-only comparison |
| GET | `/export?format=csv` | Citation line + CSV header; missing measurements not fabricated |
| GET | `/export?format=json` | Metadata and empty tests array |
| POST | `/chat` | `text/event-stream` |

Chat request: `{"question":"How does airflow affect extinction?","investigation_ids":["PSI-69"]}`.
Question must contain a non-whitespace character and be at most 2000 characters.
Unknown investigation IDs return 404; invalid inputs return 422.

SSE uses UTF-8 and LF (`\n`) with a blank line terminating each frame:

```text
event: progress
data: {"stage":"retrieval","message":"Offline contract mock; no LLM called."}

event: answer
data: {"text":"Insufficient evidence...","status":"insufficient_evidence","mode":"mock","citations":[]}

event: done
data: {"finish_reason":"insufficient_evidence"}

```

Payload schemas are `ProgressEvent`, `AnswerEvent`, `DoneEvent` in OpenAPI components;
`x-sse-events` maps event names to these schemas. `answer` carries the complete answer,
not token deltas. There is exactly one final `done`. UI code must buffer arbitrary
network boundaries and decode UTF-8 incrementally. Errors before streaming use HTTP
errors. A post-stream failure should terminate with `done.finish_reason=error`.
Production error recovery, rate limiting and token streaming are Phase 6.

Fixtures: `snapshots/sample/responses.json`, `snapshots/sample/chat.sse`, and
`web/public/fixtures.json`. Use `VITE_DATA_MODE=mock` (default) or `api` with
`VITE_API_BASE_URL`. TypeScript declarations are generated from OpenAPI.
