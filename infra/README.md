# Azure setup (build-steps Phases 0, 9, 11)

A person runs everything here: it creates billable resources. `provision.sh` is safe to
re-run; it skips what already exists. Nothing in this folder has been run yet.

| Status | Item |
| --- | --- |
| ☐ | Space Apps Global Offer claimed, Azure subscription active |
| ☐ | Region chosen (both models available): **not selected yet** |
| ☐ | `core` run: resource group, monitoring, storage, Azure OpenAI + 2 deployments |
| ☐ | Budget alert set ($20/month) |
| ☐ | `apps` run: Container Apps environment, API app, Static Web App |
| ☐ | Custom domain + certificates |

## 1. Account (portal, about 15 min)

1. spaceappschallenge.org → 2026 Global Offers → claim **Microsoft (Azure)** and **GoDaddy**.
   If sign-up rejects your country, post in the Global Offers discussion at once.
2. portal.azure.com → **Subscriptions**: one subscription shows as *Active*.
3. Open **Cloud Shell** (the `>_` icon at the top of the portal), choose **Bash**. It has
   the Azure CLI already signed in, so nothing needs installing on a laptop.

## 2. Configure and check (Cloud Shell, read-only)

```bash
git clone https://github.com/talhaadil48/firelens.git && cd firelens
cp infra/.env.azure.example infra/.env.azure
nano infra/.env.azure            # pick LOCATION; make STORAGE and AOAI names unique
bash infra/provision.sh check
```

`check` creates nothing. It lists the model versions and SKUs your region offers for
`gpt-4.1-mini` and `text-embedding-3-small`. If either is missing, try another region
(`eastus2`, `swedencentral`, `eastus`, `westus3`). Copy the exact version and SKU it
prints into `CHAT_MODEL_VERSION` / `CHAT_SKU` and `EMBED_MODEL_VERSION` / `EMBED_SKU`.

## 3. Core resources (needed before snapshot freeze G1)

```bash
bash infra/provision.sh core     # ~5 min
bash infra/provision.sh env      # writes the endpoint + key into .env (key not printed)
```

`core` creates `firelens-rg` with Log Analytics, Application Insights, the storage account
and private `snapshots` container, and Azure OpenAI with the `chat` and `embed`
deployments. It also gives *you* "Storage Blob Data Contributor" and "Cognitive Services
OpenAI User", so you can upload snapshots and call the models with `az login`.

Getting the key to the laptop that builds the snapshot: either run `env` in a local
clone (Azure CLI installed, `az login`), or copy the `AZURE_OPENAI_*` lines from the
Cloud Shell `.env` into the laptop's `.env` by hand. Never paste the key into chat,
issues or commits. `docker compose up` passes `.env` to the API container.

**Budget alert (portal, 2 min):** Cost Management → Budgets → Add → scope `firelens-rg`,
monthly, $20, alert at 80 % and 100 % to the team email.

## 4. Apps (after the API image is in GHCR)

The Phase 10 workflow pushes `ghcr.io/talhaadil48/firelens-api`. Make the package
**public** (GitHub → Packages → firelens-api → Package settings → Change visibility):
the code is MIT and the data CC0, and a public image needs no registry password.

```bash
bash infra/provision.sh apps     # Container Apps env, firelens-api (0-2 replicas), firelens-web
bash infra/provision.sh secrets  # SWA deploy token + API URL into GitHub (needs gh auth login)
bash infra/provision.sh status   # resources and public URLs
```

The API app gets a system-assigned managed identity with "Cognitive Services OpenAI
User" on Azure OpenAI and "Storage Blob Data Reader" on storage, so production has
**no API keys**. After the first run, put the Static Web App URL into `CORS_ORIGINS` and
run `apps` again.

## What maps where

| Local | Azure | Name |
| --- | --- | --- |
| `web/` (Vite dev server) | Static Web Apps, Free | `firelens-web` |
| `api/` image (`make docker-api`) | Container App, 0-2 replicas, port 8000 | `firelens-api` |
| `snapshots/<id>/` + `latest.json` | Blob container (image keeps a baked-in copy) | `<STORAGE>/snapshots` |
| `api/llm.py` provider `mock` | Azure OpenAI: `chat`, `embed` deployments | `<AOAI>` |
| `.env` | Container App env vars + managed identity | |
| `sync/` (Phase 12, optional) | Container Apps Job, cron `0 22 * * *` UTC = 03:00 PKT | `firelens-sync` |
| `docker/`, `compose.yaml` | not deployed (local development only) | |

## Domain (Phase 11, a person, GoDaddy panel)

- `www` CNAME → Static Web App default host, plus its validation TXT record.
- `api` CNAME → Container App FQDN, plus TXT `asuid.api` = the app's domain verification ID.
- Add both custom domains in Azure (free managed certificates), forward the bare domain to
  `https://www.`, set `CORS_ORIGINS='["https://www.<domain>"]'` and re-run `apps`.
