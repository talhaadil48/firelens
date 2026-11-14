#!/usr/bin/env bash
# FireLens Azure provisioning (build-steps Phase 9). A PERSON runs this; it creates
# billable resources in the signed-in subscription. Re-running is safe: existing
# resources are left as they are.
#
#   infra/provision.sh check     read-only: account, model availability, name clashes
#   infra/provision.sh core      resource group, monitoring, storage, Azure OpenAI + models
#   infra/provision.sh env       write the OpenAI endpoint/key into ./.env (never printed)
#   infra/provision.sh apps      Container Apps env + API app + Static Web App + roles
#   infra/provision.sh secrets   put deploy credentials into GitHub secrets (needs gh)
#   infra/provision.sh status    list what exists and the public URLs
#
# Runs in Azure Cloud Shell (bash) or anywhere with Azure CLI after `az login`.
# Settings: infra/.env.azure (copy from infra/.env.azure.example).
set -euo pipefail

here="$(cd "$(dirname "$0")" && pwd)"
root="$(cd "$here/.." && pwd)"
config="${FIRELENS_AZURE_CONFIG:-$here/.env.azure}"

say() { printf '\n== %s\n' "$*"; }
die() { printf 'ERROR: %s\n' "$*" >&2; exit 1; }

[ -f "$config" ] || die "Copy infra/.env.azure.example to infra/.env.azure and edit it."
# shellcheck disable=SC1090
set -a; source <(sed 's/[[:space:]]*#.*$//' "$config"); set +a
command -v az >/dev/null || die "Azure CLI not found. Use Azure Cloud Shell or install az."
az config set extension.use_dynamic_install=yes_without_prompt --only-show-errors >/dev/null

exists() { "$@" --only-show-errors -o none >/dev/null 2>&1; }
me() { az ad signed-in-user show --query id -o tsv 2>/dev/null || true; }

grant() { # grant <principal-id> <principal-type> <role> <scope>
  [ -n "$1" ] || { echo "  (skipped '$3': no principal id)"; return; }
  az role assignment create --assignee-object-id "$1" --assignee-principal-type "$2" \
    --role "$3" --scope "$4" --only-show-errors -o none
  echo "  role '$3' -> $2 $1"
}

check() {
  say "Account"
  az account show --query "{subscription:name, id:id, state:state, user:user.name}" -o table
  say "Resource providers (core registers any that are not Registered)"
  for ns in Microsoft.App Microsoft.OperationalInsights Microsoft.Insights \
            Microsoft.CognitiveServices Microsoft.Storage Microsoft.Web; do
    printf '  %-32s %s\n' "$ns" "$(az provider show -n "$ns" --query registrationState -o tsv)"
  done
  say "Models in $LOCATION (need both $CHAT_MODEL and $EMBED_MODEL)"
  az cognitiveservices model list -l "$LOCATION" \
    --query "[?model.name=='$CHAT_MODEL' || model.name=='$EMBED_MODEL'].{model:model.name, version:model.version, skus:join(', ', model.skus[].name)}" \
    -o table
  say "Name availability"
  az storage account check-name -n "$STORAGE" --query "{storage:'$STORAGE', available:nameAvailable, reason:reason}" -o table
  if exists az cognitiveservices account show -g "$RG" -n "$AOAI"; then
    echo "  $AOAI already exists in $RG (fine)"
  else
    code=$(curl -s -o /dev/null -w '%{http_code}' "https://$AOAI.openai.azure.com/" || true)
    [ "$code" = "000" ] && echo "  $AOAI.openai.azure.com looks free" \
      || echo "  $AOAI.openai.azure.com answers (HTTP $code): probably taken, change AOAI"
  fi
  echo; echo "Nothing was created. Next: infra/provision.sh core"
}

core() {
  say "Registering resource providers (first time can take a few minutes)"
  for ns in Microsoft.App Microsoft.OperationalInsights Microsoft.Insights \
            Microsoft.CognitiveServices Microsoft.Storage Microsoft.Web; do
    az provider register -n "$ns" --wait --only-show-errors -o none
  done

  say "Resource group $RG ($LOCATION)"
  az group create -n "$RG" -l "$LOCATION" --tags app=firelens -o none

  say "Log Analytics $LOGS + Application Insights $APPINSIGHTS"
  az monitor log-analytics workspace create -g "$RG" -n "$LOGS" -l "$LOCATION" \
    --retention-time 30 --only-show-errors -o none
  ws_id=$(az monitor log-analytics workspace show -g "$RG" -n "$LOGS" --query id -o tsv)
  az monitor app-insights component create -g "$RG" -a "$APPINSIGHTS" -l "$LOCATION" \
    --workspace "$ws_id" --only-show-errors -o none

  say "Storage $STORAGE, container $CONTAINER (private)"
  az storage account create -g "$RG" -n "$STORAGE" -l "$LOCATION" --sku Standard_LRS \
    --kind StorageV2 --min-tls-version TLS1_2 --allow-blob-public-access false \
    --only-show-errors -o none
  az storage container-rm create -g "$RG" --storage-account "$STORAGE" -n "$CONTAINER" \
    --only-show-errors -o none
  storage_id=$(az storage account show -g "$RG" -n "$STORAGE" --query id -o tsv)
  grant "$(me)" User "Storage Blob Data Contributor" "$storage_id"  # you upload snapshots

  say "Azure OpenAI $AOAI"
  if ! exists az cognitiveservices account show -g "$RG" -n "$AOAI"; then
    az cognitiveservices account create -g "$RG" -n "$AOAI" -l "$LOCATION" --kind OpenAI \
      --sku S0 --custom-domain "$AOAI" --yes --only-show-errors -o none
  fi
  aoai_id=$(az cognitiveservices account show -g "$RG" -n "$AOAI" --query id -o tsv)
  deploy "$CHAT_DEPLOYMENT" "$CHAT_MODEL" "$CHAT_MODEL_VERSION" "$CHAT_SKU" "$CHAT_CAPACITY"
  deploy "$EMBED_DEPLOYMENT" "$EMBED_MODEL" "$EMBED_MODEL_VERSION" "$EMBED_SKU" "$EMBED_CAPACITY"
  grant "$(me)" User "Cognitive Services OpenAI User" "$aoai_id"

  say "Done. Next: infra/provision.sh env   (then set a budget alert in the portal)"
}

deploy() { # deploy <name> <model> <version> <sku> <capacity>
  if exists az cognitiveservices account deployment show -g "$RG" -n "$AOAI" --deployment-name "$1"; then
    echo "  deployment '$1' exists"; return
  fi
  az cognitiveservices account deployment create -g "$RG" -n "$AOAI" --deployment-name "$1" \
    --model-name "$2" --model-version "$3" --model-format OpenAI \
    --sku-name "$4" --sku-capacity "$5" --only-show-errors -o none
  echo "  deployment '$1' = $2 ($3, $4, ${5}K TPM)"
}

upsert() { # upsert <file> <KEY> <value>   (value never echoed)
  local file="$1" key="$2" value="$3" tmp
  tmp="$(mktemp)"
  grep -v "^$key=" "$file" > "$tmp" || true
  printf '%s=%s\n' "$key" "$value" >> "$tmp"
  mv "$tmp" "$file"
}

env_file() {
  local file="$root/.env"
  [ -f "$file" ] || cp "$root/.env.example" "$file"
  endpoint=$(az cognitiveservices account show -g "$RG" -n "$AOAI" --query properties.endpoint -o tsv)
  upsert "$file" FIRELENS_LLM_PROVIDER azure
  upsert "$file" AZURE_OPENAI_ENDPOINT "$endpoint"
  upsert "$file" AZURE_OPENAI_CHAT_DEPLOYMENT "$CHAT_DEPLOYMENT"
  upsert "$file" AZURE_OPENAI_EMBEDDING_DEPLOYMENT "$EMBED_DEPLOYMENT"
  upsert "$file" AZURE_OPENAI_API_VERSION "$OPENAI_API_VERSION"
  upsert "$file" AZURE_OPENAI_API_KEY \
    "$(az cognitiveservices account keys list -g "$RG" -n "$AOAI" --query key1 -o tsv)"
  upsert "$file" AZURE_STORAGE_ACCOUNT_URL "https://$STORAGE.blob.core.windows.net"
  upsert "$file" AZURE_STORAGE_CONTAINER "$CONTAINER"
  chmod 600 "$file" 2>/dev/null || true
  say "Wrote $file (endpoint $endpoint; key stored, not shown). It is git-ignored."
  echo "In Cloud Shell, copy these lines into .env on your laptop; never commit or paste the key."
}

apps() {
  say "Container Apps environment $ENV_NAME"
  ws_customer=$(az monitor log-analytics workspace show -g "$RG" -n "$LOGS" --query customerId -o tsv)
  if ! exists az containerapp env show -g "$RG" -n "$ENV_NAME"; then
    az containerapp env create -g "$RG" -n "$ENV_NAME" -l "$LOCATION" \
      --logs-workspace-id "$ws_customer" \
      --logs-workspace-key "$(az monitor log-analytics workspace get-shared-keys -g "$RG" -n "$LOGS" --query primarySharedKey -o tsv)" \
      --only-show-errors -o none
  fi

  say "Container App $API_APP from $API_IMAGE"
  endpoint=$(az cognitiveservices account show -g "$RG" -n "$AOAI" --query properties.endpoint -o tsv)
  insights=$(az monitor app-insights component show -g "$RG" -a "$APPINSIGHTS" --query connectionString -o tsv)
  vars=(
    FIRELENS_MODE=snapshot
    FIRELENS_LLM_PROVIDER=azure
    "AZURE_OPENAI_ENDPOINT=$endpoint"
    "AZURE_OPENAI_CHAT_DEPLOYMENT=$CHAT_DEPLOYMENT"
    "AZURE_OPENAI_EMBEDDING_DEPLOYMENT=$EMBED_DEPLOYMENT"
    "AZURE_OPENAI_API_VERSION=$OPENAI_API_VERSION"
    "AZURE_STORAGE_ACCOUNT_URL=https://$STORAGE.blob.core.windows.net"
    "AZURE_STORAGE_CONTAINER=$CONTAINER"
    "FIRELENS_CORS_ORIGINS=$CORS_ORIGINS"
    "APPLICATIONINSIGHTS_CONNECTION_STRING=$insights"
  )
  if exists az containerapp show -g "$RG" -n "$API_APP"; then
    az containerapp update -g "$RG" -n "$API_APP" --image "$API_IMAGE" \
      --set-env-vars "${vars[@]}" --only-show-errors -o none
  else
    # Public GHCR image: no registry credentials. For a private package add
    # --registry-server ghcr.io --registry-username <user> --registry-password <PAT>.
    az containerapp create -g "$RG" -n "$API_APP" --environment "$ENV_NAME" \
      --image "$API_IMAGE" --target-port 8000 --ingress external \
      --min-replicas 0 --max-replicas 2 --cpu 0.5 --memory 1.0Gi \
      --system-assigned --env-vars "${vars[@]}" --only-show-errors -o none
  fi
  principal=$(az containerapp show -g "$RG" -n "$API_APP" --query identity.principalId -o tsv)
  grant "$principal" ServicePrincipal "Cognitive Services OpenAI User" \
    "$(az cognitiveservices account show -g "$RG" -n "$AOAI" --query id -o tsv)"
  grant "$principal" ServicePrincipal "Storage Blob Data Reader" \
    "$(az storage account show -g "$RG" -n "$STORAGE" --query id -o tsv)"

  say "Static Web App $WEB_APP (Free; deployed by GitHub Actions, not linked here)"
  if ! exists az staticwebapp show -g "$RG" -n "$WEB_APP"; then
    az staticwebapp create -g "$RG" -n "$WEB_APP" -l "$WEB_LOCATION" --sku Free \
      --only-show-errors -o none
  fi
  status
  echo; echo "Next: infra/provision.sh secrets  (then add the API URL to CORS_ORIGINS and re-run apps)"
}

secrets() {
  command -v gh >/dev/null || die "GitHub CLI not found (gh auth login first)."
  say "GitHub secrets on $GITHUB_REPO (values piped, never printed)"
  az staticwebapp secrets list -g "$RG" -n "$WEB_APP" --query properties.apiKey -o tsv \
    | gh secret set AZURE_STATIC_WEB_APPS_API_TOKEN -R "$GITHUB_REPO"
  gh variable set VITE_API_BASE_URL -R "$GITHUB_REPO" \
    --body "https://$(az containerapp show -g "$RG" -n "$API_APP" --query properties.configuration.ingress.fqdn -o tsv)"
  echo "  AZURE_STATIC_WEB_APPS_API_TOKEN (secret) and VITE_API_BASE_URL (variable) set."
  echo "  Container App deploys from Actions use OIDC; see infra/README.md, Phase 10."
}

status() {
  say "Resources in $RG"
  az resource list -g "$RG" --query "[].{name:name, type:type}" -o table
  say "URLs"
  echo "  API: https://$(az containerapp show -g "$RG" -n "$API_APP" --query properties.configuration.ingress.fqdn -o tsv 2>/dev/null || echo '(not created)')"
  echo "  Web: https://$(az staticwebapp show -g "$RG" -n "$WEB_APP" --query defaultHostname -o tsv 2>/dev/null || echo '(not created)')"
}

case "${1:-}" in
  check) check ;;
  core) core ;;
  env) env_file ;;
  apps) apps ;;
  secrets) secrets ;;
  status) status ;;
  *) sed -n '2,13p' "$0"; exit 1 ;;
esac
