# FireLens on Azure (build-steps Phases 9–11)

**Region:** East US 2 (`eastus2`), resource group `firelens-rg`.
**LLM:** OpenRouter, not Azure OpenAI (see `docs/context/DECISIONS.md`). There is no
Azure OpenAI resource; step 9.3 is replaced by a Container App secret holding the
OpenRouter key.

```text
GoDaddy DNS ── www ──> Static Web App  firelens-web   (React build, Free plan)
            └─ api ──> Container App   firelens-api   (GHCR image, 0–2 replicas)
                                         │  anonymous GET every 15 min
                                         ▼
                        Storage firelensdata<sfx> / snapshots / latest.json + <id>/…
                        Log Analytics firelens-logs + App Insights firelens-insights
```

## 0. Prerequisites (once)

- Azure CLI: `winget install -e --id Microsoft.AzureCLI`, open a new terminal,
  `az login`, then `az account set --subscription <id>`. Azure Cloud Shell also works,
  but `upload` needs the local snapshot folder.
- GitHub CLI: `winget install -e --id GitHub.cli`, `gh auth login`, then
  `gh auth refresh -h github.com -s write:packages` (for `image`).
- Docker Desktop running (for `image`) and Node 20+ (for `web`).
- Run the script from **Git Bash** at the repo root: `bash infra/provision.sh <step>`.
- `cp infra/.env.azure.example infra/.env.azure` and edit: subscription id, a unique
  `STORAGE` name, `GITHUB_REPO`. It is git-ignored.
- The OpenRouter key comes from `OPENROUTER_API_KEY` in your shell or `./.env`. Set a
  credit limit on that key in the OpenRouter dashboard; it is the real cost guard.

## 1. Steps, in order

| # | Command / action | Build step | Done when |
|---|---|---|---|
| 1 | `bash infra/provision.sh check` | 0.3 | Account, providers and storage name look right. Creates nothing. |
| 2 | `bash infra/provision.sh core` | 9.1, 9.2 | RG, logs, App Insights, storage account and public-read `snapshots` container exist. |
| 3 | `bash infra/provision.sh upload` | 9.2 | Prints `public read OK`. Needs a real `snapshots/latest.json` (full `SnapshotPointer` with `files`) from `harvest.pipeline all`. |
| 4 | `bash infra/provision.sh image`, then make the package **public** once (§2) | 9.5 | `ghcr.io/<you>/firelens-api:latest` exists and is public. |
| 5 | `bash infra/provision.sh apps` | 9.3–9.6 | `curl https://<api fqdn>/meta` returns the snapshot id from step 3. |
| 6 | `bash infra/provision.sh web` | 9.6 | `https://<name>.azurestaticapps.net` loads with live data. |
| 7 | Budget alert in the portal (§5) | 9.7 | Alert e-mail configured. |
| 8 | `bash infra/provision.sh github`; owner adds the printed values | 10.2, 10.3 | Secrets and variables are on the repo; Actions deploy from `main`. |
| 9 | Custom domain (§3) | 11 | `https://www.<domain>` and `https://api.<domain>` work. |

`bash infra/provision.sh status` prints what exists and the URLs at any time. Every
step is safe to re-run; re-running `apps` also rotates the OpenRouter secret and
updates env vars.

## 2. Deploying before and after `main` is updated

`main` still holds the Phase 2 API, so an image built from it would serve sample data
only. Until the Phase 6–9 branches are merged, deploy from your laptop:

- **API:** `bash infra/provision.sh image` builds `api/Dockerfile` from the checked-out
  branch and pushes `API_IMAGE` plus a `:<git sha>` tag. Docker logs in with your `gh`
  token; if the push is denied, run `gh auth refresh -h github.com -s write:packages`.
  After the first push: GitHub → your profile → Packages → `firelens-api` → Package
  settings → Change visibility → **Public**. Then `bash infra/provision.sh apps` (or,
  for later images, `az containerapp update -g firelens-rg -n firelens-api --image <tag>`).
- **Web:** `bash infra/provision.sh web` builds `web/` with `VITE_DATA_MODE=api` and the
  API URL, then uploads `web/dist` with the Static Web Apps CLI. Re-run after each
  web change. `web/.env.local` is ignored for this build.

After the merge, `.github/workflows/deploy-api.yml` and `deploy-web.yml` take over
on every push to `main` (they stay idle until step 8 sets the repo variables). The
owner makes `ghcr.io/talhaadil48/firelens-api` public after its first build, then
set `API_IMAGE` to it and re-run `apps`.

## 3. Custom domain (GoDaddy, Phase 11)

Do the API first; the Static Web App can then switch CORS in one go.

**API (`api.<domain>`)**

1. `az containerapp show -g firelens-rg -n firelens-api --query properties.customDomainVerificationId -o tsv`
2. GoDaddy DNS: `CNAME api → <api fqdn>` and `TXT asuid.api → <verification id>`.
3. `az containerapp hostname add -g firelens-rg -n firelens-api --hostname api.<domain>`
   then `az containerapp hostname bind -g firelens-rg -n firelens-api --hostname api.<domain> --environment firelens-env --validation-method CNAME`
   (issues the free managed certificate; can take 5–15 minutes).

**Web (`www.<domain>`)**

1. GoDaddy DNS: `CNAME www → <web default hostname>`.
2. `az staticwebapp hostname set -g firelens-rg -n firelens-web --hostname www.<domain>`
3. GoDaddy → Forwarding: bare domain → `https://www.<domain>` (permanent 301).

**Switch over**

1. In `infra/.env.azure`: `CORS_ORIGINS='["https://www.<domain>","https://<web default hostname>"]'`, then `bash infra/provision.sh apps`.
2. Set `WEB_API_URL=https://api.<domain>` in `infra/.env.azure` and run
   `bash infra/provision.sh web` (after the merge: set the GitHub variable
   `VITE_API_BASE_URL` to the same value and re-run **Deploy web**).
3. Smoke test from a phone on mobile data. Keep the Azure default URLs as backup links.

## 4. Sync job, snapshot formats and guarded deploys (Phase 12)

**Snapshot formats.** `python -m api.snapshot_format` prints a 12-character id hashed from
every schema the API reads from a snapshot. The API reads
`snapshots/formats/<id>/latest.json` first and the legacy root `latest.json` only if that is
missing. The sync job writes **only** the pointer for its own format and new
`<snapshot_id>/` folders; it never overwrites the legacy pointer or deletes anything. A
model change therefore gets its own pointer instead of breaking the running API.

| Command | What it does |
|---|---|
| `bash infra/provision.sh sync` | Creates/updates the Container Apps Job `firelens-sync` (cron `0 22 * * *` UTC = 03:00 PKT, 30 min timeout, no retries) with a system identity that has Storage Blob Data Contributor on the account. Needs `SYNC_IMAGE` (public GHCR package). |
| `bash infra/provision.sh sync-run [--force\|--dry-run]` | Starts one execution and waits. The last log line is a JSON result: `published`, `no_change`, `dry_run` or `refused`. |
| `bash infra/provision.sh staging <api image>` | Private staging API `firelens-api-staging` (0–1 replicas) for branch deploys. |
| `uv run python -m scripts.check_snapshot --blob https://<account>.blob.core.windows.net/snapshots` | Checks the published snapshot for this code's format with the API's own loaders. Exit 0 ok, 1 invalid, 2 not published yet, 3 unreachable. |

The job rebuilds when the PSI Combustion catalogue changes, when nothing is published for
its format, every 7 days, or with `--force`. It publishes only if the new snapshot passes
the checker and is not smaller than the published one (≥ the same investigations, ≥ 90 %
of test rows; `--force` skips this size guard, never the validation).

**Deploy pipeline** (`.github/workflows/deploy.yml`, replaces `deploy-api.yml` and
`deploy-web.yml`): CI → API + sync images (`:<sha>`) → snapshot gate (if no valid
snapshot exists for the new format, run the sync job with the new image and wait; fail
before touching the API otherwise) → switch the API → smoke test `/meta` (expected
snapshot, no snapshot warnings) and the main endpoints → **automatic rollback** to the
previous image on any failure → web (only after a green API). Pushes to
`feature/phase-12-sync` deploy to the staging API only; a commit message containing
`[simulate-smoke-failure]` drills the rollback there.

**Freeze switch:** repo variable `DEPLOY_FREEZE=true` skips every production deploy
(judging). Optional variables, defaults in brackets: `AZURE_SYNC_JOB` [firelens-sync],
`AZURE_STAGING_API_APP` [firelens-api-staging], `SNAPSHOT_CONTAINER_URL`
[https://firelensdata.blob.core.windows.net/snapshots].

**Manual rollback:** `az containerapp update -g firelens-rg -n firelens-api --image <previous image>`.
The legacy `latest.json` and every earlier snapshot folder stay in Blob.

## 5. Budget alert (9.7)

Portal → Cost Management → Budgets → Add: scope `firelens-rg`, monthly, $20, alerts at
50 % and 100 % actual to your e-mail. Sponsorship subscriptions may not support budgets;
then check Cost analysis by hand weekly (build step 15.2).

## Notes and known gaps

- **Blob access is anonymous read.** `api/snapshot.py` fetches with plain HTTPS GETs and
  has no managed-identity code, so the container is public-read. It only holds CC0
  PSI-derived snapshot files; writes need the account key or an RBAC role.
- **Embeddings.** With `FIRELENS_LLM_PROVIDER=openrouter`, `api/llm.py` uses the
  deterministic local embedding for both chunks and questions. No embedding service is
  provisioned. Retrieval quality is a code concern, not an infra one.
- **Snapshot baked into the image** is only `snapshots/sample` (real snapshots are
  git-ignored). If Blob is unreachable the API serves the sample fallback; `/meta` warns.
- **Cold start.** `--min-replicas 0` keeps cost near zero; the first request after
  idle takes a few seconds. Set `--min-replicas 1` for judging day if needed.
- **Sync job (Phase 12)**: see §4.
