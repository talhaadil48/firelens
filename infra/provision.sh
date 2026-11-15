#!/usr/bin/env bash
# FireLens Azure provisioning (build-steps Phase 9, OpenRouter edition). A PERSON runs
# this; it creates billable resources in the signed-in subscription. Re-running is safe.
#
#   infra/provision.sh check          read-only: account, providers, name clashes
#   infra/provision.sh core           resource group, logs, storage + snapshots container
#   infra/provision.sh upload         upload snapshots/<id>/ then snapshots/latest.json
#   infra/provision.sh image          build api/Dockerfile and push $API_IMAGE to GHCR
#   infra/provision.sh apps           Container Apps env, API app, Static Web App
#   infra/provision.sh web            build web/ against the live API and upload it
#   infra/provision.sh github         OIDC deploy identity + GitHub secrets/variables
#   infra/provision.sh sync           Container Apps Job $SYNC_JOB (nightly 03:00 PKT) from $SYNC_IMAGE
#   infra/provision.sh sync-run [--force|--dry-run]  start one sync execution and wait for it
#   infra/provision.sh staging <img>  private staging API $STAGING_API_APP on <img> (scale to zero)
#   infra/provision.sh status         what exists and the public URLs
#
# Runs in Git Bash, WSL, macOS/Linux or Azure Cloud Shell after `az login`.
# `image` needs Docker and `gh auth login` with the write:packages scope; `web` needs Node.
# Settings: infra/.env.azure (copy from infra/.env.azure.example).
set -euo pipefail
export MSYS_NO_PATHCONV=1   # Git Bash: keep /subscriptions/... scopes intact

here="$(cd "$(dirname "$0")" && pwd)"
root="$(cd "$here/.." && pwd)"
config="${FIRELENS_AZURE_CONFIG:-$here/.env.azure}"

say() { printf '\n== %s\n' "$*"; }
die() { printf 'ERROR: %s\n' "$*" >&2; exit 1; }

[ -f "$config" ] || die "Copy infra/.env.azure.example to infra/.env.azure and edit it."
# shellcheck disable=SC1090
set -a; source <(sed -e 's/\r$//' -e 's/[[:space:]]*#.*$//' "$config"); set +a
command -v az >/dev/null || die "Azure CLI not found. Install it or use Azure Cloud Shell."
az config set extension.use_dynamic_install=yes_without_prompt --only-show-errors >/dev/null
[ -n "${SUBSCRIPTION:-}" ] && az account set --subscription "$SUBSCRIPTION"

PROVIDERS=(Microsoft.App Microsoft.OperationalInsights Microsoft.Insights Microsoft.Storage Microsoft.Web)
BLOB_URL="https://$STORAGE.blob.core.windows.net"
SYNC_JOB="${SYNC_JOB:-firelens-sync}"
STAGING_API_APP="${STAGING_API_APP:-firelens-api-staging}"
SYNC_CRON="0 22 * * *"   # 22:00 UTC = 03:00 PKT (Container Apps cron is UTC)

exists() { "$@" --only-show-errors -o none >/dev/null 2>&1; }
winpath() { if command -v cygpath >/dev/null; then cygpath -w "$1"; else printf '%s' "$1"; fi; }

grant() { # grant <principal-id> <principal-type> <role> <scope>
  [ -n "$1" ] || { echo "  (skipped '$3': no principal id)"; return; }
  az role assignment create --assignee-object-id "$1" --assignee-principal-type "$2" \
    --role "$3" --scope "$4" --only-show-errors -o none
  echo "  role '$3' -> $2"
}

openrouter_key() { # from the environment, else ./.env; never printed
  local key="${OPENROUTER_API_KEY:-}"
  if [ -z "$key" ] && [ -f "$root/.env" ]; then
    key=$(sed -n 's/^OPENROUTER_API_KEY=//p' "$root/.env" | tail -1 | tr -d "\r\"'")
  fi
  printf '%s' "$key"
}

api_fqdn() { az containerapp show -g "$RG" -n "$API_APP" --query properties.configuration.ingress.fqdn -o tsv 2>/dev/null || true; }
web_host() { az staticwebapp show -g "$RG" -n "$WEB_APP" --query defaultHostname -o tsv 2>/dev/null || true; }

check() {
  say "Account"
  az account show --query "{subscription:name, id:id, state:state, user:user.name}" -o table
  say "Resource providers (core registers any that are not Registered)"
  for ns in "${PROVIDERS[@]}"; do
    printf '  %-30s %s\n' "$ns" "$(az provider show -n "$ns" --query registrationState -o tsv)"
  done
  say "Storage name"
  if exists az storage account show -g "$RG" -n "$STORAGE"; then
    echo "  $STORAGE already exists in $RG (fine)"
  else
    az storage account check-name -n "$STORAGE" --query "{name:'$STORAGE', available:nameAvailable, reason:reason}" -o table 2>/dev/null \
      || echo "  cannot check yet: Microsoft.Storage is not registered ('core' registers it)"
  fi
  say "OpenRouter key"
  [ -n "$(openrouter_key)" ] && echo "  found (not shown)" || echo "  MISSING: set OPENROUTER_API_KEY or put it in ./.env"
  echo; echo "Nothing was created. Next: infra/provision.sh core"
}

core() {
  say "Registering resource providers (first time can take a few minutes)"
  for ns in "${PROVIDERS[@]}"; do az provider register -n "$ns" --wait --only-show-errors -o none; done

  say "Resource group $RG ($LOCATION)"
  az group create -n "$RG" -l "$LOCATION" --tags app=firelens -o none

  say "Log Analytics $LOGS + Application Insights $APPINSIGHTS"
  exists az monitor log-analytics workspace show -g "$RG" -n "$LOGS" || \
    az monitor log-analytics workspace create -g "$RG" -n "$LOGS" -l "$LOCATION" \
      --retention-time 30 --only-show-errors -o none
  ws_id=$(az monitor log-analytics workspace show -g "$RG" -n "$LOGS" --query id -o tsv)
  exists az monitor app-insights component show -g "$RG" -a "$APPINSIGHTS" || \
    az monitor app-insights component create -g "$RG" -a "$APPINSIGHTS" -l "$LOCATION" \
      --workspace "$ws_id" --only-show-errors -o none

  # The API fetches snapshot files with anonymous HTTPS GETs (api/snapshot.py), so the
  # container is public-read. It only ever holds CC0 PSI-derived snapshot files.
  say "Storage $STORAGE, container $CONTAINER (anonymous blob read; writes need the account key)"
  if exists az storage account show -g "$RG" -n "$STORAGE"; then
    az storage account update -g "$RG" -n "$STORAGE" --allow-blob-public-access true \
      --only-show-errors -o none
  else
    az storage account create -g "$RG" -n "$STORAGE" -l "$LOCATION" --sku Standard_LRS \
      --kind StorageV2 --min-tls-version TLS1_2 --allow-blob-public-access true \
      --only-show-errors -o none
  fi
  if exists az storage container-rm show -g "$RG" --storage-account "$STORAGE" -n "$CONTAINER"; then
    az storage container-rm update -g "$RG" --storage-account "$STORAGE" -n "$CONTAINER" \
      --public-access blob --only-show-errors -o none
  else
    az storage container-rm create -g "$RG" --storage-account "$STORAGE" -n "$CONTAINER" \
      --public-access blob --only-show-errors -o none
  fi
  say "Done. Next: infra/provision.sh upload"
}

upload() {
  local pointer="$root/snapshots/latest.json" id src
  [ -f "$pointer" ] || die "No snapshots/latest.json. Build a snapshot first (make snapshot)."
  grep -q '"files"' "$pointer" || die "snapshots/latest.json lacks 'files': it must be a full api.models.SnapshotPointer."
  id=$(sed -n 's/.*"snapshot_id"[[:space:]]*:[[:space:]]*"\([^"]*\)".*/\1/p' "$pointer" | head -1)
  src="$root/snapshots/$id"
  [ -n "$id" ] && [ -d "$src" ] || die "Snapshot folder snapshots/$id not found."

  AZURE_STORAGE_ACCOUNT="$STORAGE"
  AZURE_STORAGE_KEY=$(az storage account keys list -g "$RG" -n "$STORAGE" --query "[0].value" -o tsv)
  export AZURE_STORAGE_ACCOUNT AZURE_STORAGE_KEY

  say "Uploading snapshots/$id -> $CONTAINER/$id/"
  az storage blob upload-batch -d "$CONTAINER" -s "$(winpath "$src")" --destination-path "$id" \
    --overwrite --only-show-errors -o none
  say "Uploading the pointer last: $CONTAINER/latest.json"
  az storage blob upload -c "$CONTAINER" -n latest.json -f "$(winpath "$pointer")" --overwrite \
    --content-type application/json --content-cache-control no-cache --only-show-errors -o none
  unset AZURE_STORAGE_KEY

  if command -v curl >/dev/null && curl -fsS "$BLOB_URL/$CONTAINER/latest.json" >/dev/null; then
    echo "  public read OK: $BLOB_URL/$CONTAINER/latest.json"
  else
    echo "  WARNING: $BLOB_URL/$CONTAINER/latest.json is not publicly readable yet."
  fi
  echo "The API picks the new pointer up within 15 minutes (or on its next cold start)."
}

image() {
  command -v docker >/dev/null || die "Docker not found."
  docker info >/dev/null 2>&1 || die "Docker is not running. Start Docker Desktop."
  [ "$API_IMAGE" = "$(printf '%s' "$API_IMAGE" | tr '[:upper:]' '[:lower:]')" ] \
    || die "API_IMAGE must be lowercase (GHCR rule): $API_IMAGE"
  local repo="${API_IMAGE%:*}" sha
  sha=$(git -C "$(winpath "$root")" rev-parse --short HEAD)

  say "Building $API_IMAGE (also tagged :$sha) from api/Dockerfile"
  docker build -f "$(winpath "$root/api/Dockerfile")" -t "$API_IMAGE" -t "$repo:$sha" "$(winpath "$root")"

  if command -v gh >/dev/null && gh auth status >/dev/null 2>&1; then
    say "Logging Docker in to ghcr.io with the gh token (not shown)"
    gh auth token | docker login ghcr.io -u "$(gh api user --jq .login)" --password-stdin >/dev/null
  else
    echo "  gh not logged in; using an existing 'docker login ghcr.io'."
  fi
  say "Pushing"
  docker push -q "$API_IMAGE" && docker push -q "$repo:$sha" \
    || die "Push denied. Run: gh auth refresh -h github.com -s write:packages   (then retry)"
  echo; echo "Pushed $API_IMAGE and $repo:$sha."
  echo "First push only: GitHub -> your profile -> Packages -> ${repo##*/} -> Package settings"
  echo "-> Change visibility -> Public, so Azure can pull it without credentials."
}

web() {
  command -v npm >/dev/null || die "Node.js/npm not found."
  local api="${WEB_API_URL:-}"
  if [ -z "$api" ]; then
    local fqdn; fqdn="$(api_fqdn)"
    [ -n "$fqdn" ] || die "API app not found. Run 'apps' first or set WEB_API_URL in infra/.env.azure."
    api="https://$fqdn"
  fi
  exists az staticwebapp show -g "$RG" -n "$WEB_APP" || die "Static Web App $WEB_APP not found. Run 'apps' first."

  say "Building web/ against $api"
  # Variables already in the environment override web/.env.local, so a local preview
  # setting can never leak into the deployed build.
  ( cd "$root/web"
    [ -d node_modules ] || npm ci --no-audit --no-fund
    VITE_DATA_MODE=api VITE_API_BASE_URL="$api" npm run build )

  say "Uploading web/dist to $WEB_APP (deployment token fetched, not shown)"
  SWA_CLI_DEPLOYMENT_TOKEN=$(az staticwebapp secrets list -g "$RG" -n "$WEB_APP" --query properties.apiKey -o tsv)
  export SWA_CLI_DEPLOYMENT_TOKEN
  ( cd "$root/web" && npx --yes @azure/static-web-apps-cli@2 deploy dist --env production )
  unset SWA_CLI_DEPLOYMENT_TOKEN
  echo; echo "Live at https://$(web_host)   (API: $api)"
}

api_vars() { # api_vars <cors-json> <insights-connection-string>: fills API_VARS
  API_VARS=(
    FIRELENS_MODE=snapshot
    FIRELENS_LLM_PROVIDER=openrouter
    OPENROUTER_API_KEY=secretref:openrouter-key
    "OPENROUTER_MODEL=$OPENROUTER_MODEL"
    "AZURE_STORAGE_ACCOUNT_URL=$BLOB_URL"
    "AZURE_STORAGE_CONTAINER=$CONTAINER"
    "FIRELENS_CORS_ORIGINS=$1"
    # Uvicorn takes the client IP from X-Forwarded-For set by the Container Apps
    # ingress, so the per-IP /chat limit is per visitor rather than global.
    "FORWARDED_ALLOW_IPS=*"
    "APPLICATIONINSIGHTS_CONNECTION_STRING=$2"
  )
}

apps() {
  local key; key="$(openrouter_key)"
  [ -n "$key" ] || die "OpenRouter key missing: export OPENROUTER_API_KEY or add it to ./.env"

  say "Static Web App $WEB_APP (Free; deployed by GitHub Actions)"
  exists az staticwebapp show -g "$RG" -n "$WEB_APP" || \
    az staticwebapp create -g "$RG" -n "$WEB_APP" -l "$WEB_LOCATION" --sku Free --only-show-errors -o none
  local web; web="$(web_host)"
  local cors="${CORS_ORIGINS:-}"
  [ -n "$cors" ] || cors="[\"https://$web\",\"http://localhost:5173\"]"

  say "Container Apps environment $ENV_NAME"
  if ! exists az containerapp env show -g "$RG" -n "$ENV_NAME"; then
    az containerapp env create -g "$RG" -n "$ENV_NAME" -l "$LOCATION" \
      --logs-workspace-id "$(az monitor log-analytics workspace show -g "$RG" -n "$LOGS" --query customerId -o tsv)" \
      --logs-workspace-key "$(az monitor log-analytics workspace get-shared-keys -g "$RG" -n "$LOGS" --query primarySharedKey -o tsv)" \
      --only-show-errors -o none
  fi

  say "Container App $API_APP from $API_IMAGE"
  local insights
  insights=$(az monitor app-insights component show -g "$RG" -a "$APPINSIGHTS" --query connectionString -o tsv)
  api_vars "$cors" "$insights"
  local vars=("${API_VARS[@]}")
  if exists az containerapp show -g "$RG" -n "$API_APP"; then
    az containerapp secret set -g "$RG" -n "$API_APP" --secrets "openrouter-key=$key" \
      --only-show-errors -o none
    az containerapp update -g "$RG" -n "$API_APP" --image "$API_IMAGE" \
      --set-env-vars "${vars[@]}" --only-show-errors -o none
  else
    # Public GHCR image: no registry credentials needed. For a private package add
    # --registry-server ghcr.io --registry-username <user> --registry-password <PAT>.
    az containerapp create -g "$RG" -n "$API_APP" --environment "$ENV_NAME" \
      --image "$API_IMAGE" --target-port 8000 --ingress external \
      --min-replicas 0 --max-replicas 2 --cpu 0.5 --memory 1.0Gi \
      --secrets "openrouter-key=$key" --env-vars "${vars[@]}" --only-show-errors -o none
  fi
  echo "  CORS: $cors"
  status
  echo; echo "Next: curl https://$(api_fqdn)/meta   then   infra/provision.sh web"
}

github() {
  local sub tenant app_id sp_id rg_id
  sub=$(az account show --query id -o tsv)
  tenant=$(az account show --query tenantId -o tsv)

  say "Entra app $DEPLOY_APP (OIDC for $GITHUB_REPO, branch main)"
  app_id=$(az ad app list --display-name "$DEPLOY_APP" --query "[0].appId" -o tsv)
  [ -n "$app_id" ] || app_id=$(az ad app create --display-name "$DEPLOY_APP" --query appId -o tsv)
  exists az ad sp show --id "$app_id" || az ad sp create --id "$app_id" --only-show-errors -o none
  sp_id=$(az ad sp show --id "$app_id" --query id -o tsv)
  federate() { # federate <credential-name> <subject>
    [ -n "$(az ad app federated-credential list --id "$app_id" --query "[?name=='$1'].name" -o tsv)" ] && return
    az ad app federated-credential create --id "$app_id" --only-show-errors -o none --parameters \
      "{\"name\":\"$1\",\"issuer\":\"https://token.actions.githubusercontent.com\",\"subject\":\"$2\",\"audiences\":[\"api://AzureADTokenExchange\"]}"
    echo "  OIDC subject $2"
  }
  federate github-main "repo:$GITHUB_REPO:ref:refs/heads/main"
  # GitHub may send the subject with immutable IDs: repo:<owner>@<id>/<repo>@<id>:ref:...
  local ids
  ids=$(gh api "repos/$GITHUB_REPO" --jq '"\(.owner.login)@\(.owner.id)/\(.name)@\(.id)"' 2>/dev/null || true)
  if [ -n "$ids" ]; then
    federate github-main-ids "repo:$ids:ref:refs/heads/main"
  else
    echo "  (gh unavailable: add the ID-form subject by hand if azure/login reports AADSTS700213)"
  fi
  rg_id=$(az group show -n "$RG" --query id -o tsv)
  grant "$sp_id" ServicePrincipal Contributor "$rg_id"

  local api="https://$(api_fqdn)" admin=false
  if command -v gh >/dev/null && gh auth status >/dev/null 2>&1; then
    admin=$(gh api "repos/$GITHUB_REPO" --jq .permissions.admin 2>/dev/null || echo false)
  fi
  if [ "$admin" = "true" ]; then
    say "GitHub secrets and variables on $GITHUB_REPO (values piped, never printed)"
    gh secret set AZURE_CLIENT_ID -R "$GITHUB_REPO" --body "$app_id"
    gh secret set AZURE_TENANT_ID -R "$GITHUB_REPO" --body "$tenant"
    gh secret set AZURE_SUBSCRIPTION_ID -R "$GITHUB_REPO" --body "$sub"
    az staticwebapp secrets list -g "$RG" -n "$WEB_APP" --query properties.apiKey -o tsv \
      | gh secret set AZURE_STATIC_WEB_APPS_API_TOKEN -R "$GITHUB_REPO"
    gh variable set AZURE_RG -R "$GITHUB_REPO" --body "$RG"
    gh variable set AZURE_API_APP -R "$GITHUB_REPO" --body "$API_APP"
    gh variable set VITE_API_BASE_URL -R "$GITHUB_REPO" --body "$api"
    echo "  done"
  else
    # On a personal-account repo only the owner can manage Actions secrets.
    say "No admin rights on $GITHUB_REPO. Send these to the owner for Settings -> Secrets and variables -> Actions"
    echo "  secret   AZURE_CLIENT_ID          = $app_id"
    echo "  secret   AZURE_TENANT_ID          = $tenant"
    echo "  secret   AZURE_SUBSCRIPTION_ID    = $sub"
    echo "  secret   AZURE_STATIC_WEB_APPS_API_TOKEN = output of:"
    echo "           az staticwebapp secrets list -g $RG -n $WEB_APP --query properties.apiKey -o tsv"
    echo "  variable AZURE_RG                 = $RG"
    echo "  variable AZURE_API_APP            = $API_APP"
    echo "  variable VITE_API_BASE_URL        = $api"
    echo "Send the deployment token privately (direct message), never in an issue, PR or chat channel."
  fi
}

sync() {
  local image="${SYNC_IMAGE:-}"
  [ -n "$image" ] || die "Set SYNC_IMAGE in infra/.env.azure (e.g. ghcr.io/talhaadil48/firelens-sync:<sha>); the package must be public."
  local vars=("AZURE_STORAGE_ACCOUNT_URL=$BLOB_URL" "AZURE_STORAGE_CONTAINER=$CONTAINER")

  say "Container Apps Job $SYNC_JOB from $image (cron '$SYNC_CRON' UTC = 03:00 PKT)"
  if exists az containerapp job show -g "$RG" -n "$SYNC_JOB"; then
    az containerapp job update -g "$RG" -n "$SYNC_JOB" --image "$image" \
      --cron-expression "$SYNC_CRON" --replica-timeout 1800 --replica-retry-limit 0 \
      --set-env-vars "${vars[@]}" --only-show-errors -o none
  else
    az containerapp job create -g "$RG" -n "$SYNC_JOB" --environment "$ENV_NAME" \
      --trigger-type Schedule --cron-expression "$SYNC_CRON" \
      --replica-timeout 1800 --replica-retry-limit 0 --parallelism 1 --replica-completion-count 1 \
      --image "$image" --container-name "$SYNC_JOB" --cpu 1.0 --memory 2.0Gi \
      --env-vars "${vars[@]}" --mi-system-assigned --only-show-errors -o none
  fi
  # Writes go through the job's own identity; nothing else gets write access.
  local principal storage_id
  principal=$(az containerapp job show -g "$RG" -n "$SYNC_JOB" --query identity.principalId -o tsv)
  storage_id=$(az storage account show -g "$RG" -n "$STORAGE" --query id -o tsv)
  grant "$principal" ServicePrincipal "Storage Blob Data Contributor" "$storage_id"
  echo "  Role assignments can take a few minutes to apply. Next: infra/provision.sh sync-run"
}

sync_run() { # sync_run [--force|--dry-run]
  local args=(--container-name "$SYNC_JOB")
  [ -n "${1:-}" ] && args+=(--args "$1")
  say "Starting $SYNC_JOB ${1:-}"
  local exec status
  exec=$(az containerapp job start -g "$RG" -n "$SYNC_JOB" "${args[@]}" --query name -o tsv)
  echo "  execution $exec"
  for _ in $(seq 1 80); do
    status=$(az containerapp job execution show -g "$RG" -n "$SYNC_JOB" \
      --job-execution-name "$exec" --query properties.status -o tsv)
    printf '  %s %s\n' "$(date +%H:%M:%S)" "$status"
    case "$status" in Succeeded|Failed|Stopped|Degraded) break ;; esac
    sleep 15
  done
  echo "  Logs (the last line is the JSON result):"
  echo "    az containerapp job logs show -g $RG -n $SYNC_JOB --execution $exec --container $SYNC_JOB"
  echo "  Published pointers: $BLOB_URL/$CONTAINER/formats/<format id>/latest.json"
  [ "$status" = "Succeeded" ] || die "Execution $exec ended '$status'. Nothing the live API reads was changed."
}

staging() { # staging <api image>
  local image="${1:-}"
  [ -n "$image" ] || die "Usage: infra/provision.sh staging ghcr.io/<owner>/firelens-api:<tag>"
  local key; key="$(openrouter_key)"
  [ -n "$key" ] || die "OpenRouter key missing: export OPENROUTER_API_KEY or add it to ./.env"
  local insights
  insights=$(az monitor app-insights component show -g "$RG" -a "$APPINSIGHTS" --query connectionString -o tsv)
  api_vars "[\"http://localhost:5173\"]" "$insights"

  say "Staging API $STAGING_API_APP on $image (not linked from the website)"
  if exists az containerapp show -g "$RG" -n "$STAGING_API_APP"; then
    az containerapp secret set -g "$RG" -n "$STAGING_API_APP" --secrets "openrouter-key=$key" \
      --only-show-errors -o none
    az containerapp update -g "$RG" -n "$STAGING_API_APP" --image "$image" \
      --set-env-vars "${API_VARS[@]}" --only-show-errors -o none
  else
    az containerapp create -g "$RG" -n "$STAGING_API_APP" --environment "$ENV_NAME" \
      --image "$image" --target-port 8000 --ingress external \
      --min-replicas 0 --max-replicas 1 --cpu 0.5 --memory 1.0Gi \
      --secrets "openrouter-key=$key" --env-vars "${API_VARS[@]}" --only-show-errors -o none
  fi
  local fqdn
  fqdn=$(az containerapp show -g "$RG" -n "$STAGING_API_APP" --query properties.configuration.ingress.fqdn -o tsv)
  echo "  https://$fqdn/meta"
}

status() {
  say "Resources in $RG"
  az resource list -g "$RG" --query "[].{name:name, type:type}" -o table
  say "URLs"
  local api web; api="$(api_fqdn)"; web="$(web_host)"
  echo "  API:       $([ -n "$api" ] && echo "https://$api" || echo '(not created)')"
  echo "  Web:       $([ -n "$web" ] && echo "https://$web" || echo '(not created)')"
  echo "  Snapshots: $BLOB_URL/$CONTAINER/latest.json"
}

case "${1:-}" in
  check) check ;;
  core) core ;;
  upload) upload ;;
  image) image ;;
  apps) apps ;;
  web) web ;;
  github) github ;;
  status) status ;;
  sync) sync ;;
  sync-run) sync_run "${2:-}" ;;
  staging) staging "${2:-}" ;;
  *) sed -n '2,19p' "$0"; exit 1 ;;
esac
