#!/usr/bin/env bash
set -euo pipefail

# -- Configuration --
RESOURCE_GROUP="${AZURE_RESOURCE_GROUP:-meeting-pinger-rg}"
LOCATION="${AZURE_LOCATION:-eastus}"
ENVIRONMENT_NAME="meeting-pinger-env"
APP_NAME="meeting-pinger"
REGISTRY_NAME="${AZURE_REGISTRY_NAME:-meetingpingercr}"
IMAGE="${REGISTRY_NAME}.azurecr.io/${APP_NAME}:latest"

# -- Required env vars --
REQUIRED_VARS=(
    INTERNAL_TEAM_UTIL_SLACK_BOT_TOKEN
    INTERNAL_TEAM_UTIL_SLACK_APP_TOKEN
    INTERNAL_TEAM_UTIL_USERS_JSON
)

for var in "${REQUIRED_VARS[@]}"; do
    if [[ -z "${!var:-}" ]]; then
        echo "Error: ${var} is not set. Export it or add to .env before deploying."
        echo ""
        echo "Hint: To set INTERNAL_TEAM_UTIL_USERS_JSON from users.json:"
        echo "  export INTERNAL_TEAM_UTIL_USERS_JSON=\$(cat users.json)"
        exit 1
    fi
done

# -- Ensure resource group exists --
echo "==> Ensuring resource group '${RESOURCE_GROUP}' exists..."
az group create \
    --name "${RESOURCE_GROUP}" \
    --location "${LOCATION}" \
    --output none

# -- Ensure container registry exists --
echo "==> Ensuring container registry '${REGISTRY_NAME}' exists..."
az acr create \
    --resource-group "${RESOURCE_GROUP}" \
    --name "${REGISTRY_NAME}" \
    --sku Basic \
    --admin-enabled true \
    --output none 2>/dev/null || true

# -- Build and push image --
echo "==> Building and pushing container image..."
az acr build \
    --registry "${REGISTRY_NAME}" \
    --image "${APP_NAME}:latest" \
    . --no-logs

# -- Get registry credentials --
REGISTRY_SERVER="${REGISTRY_NAME}.azurecr.io"
REGISTRY_USERNAME=$(az acr credential show --name "${REGISTRY_NAME}" --query "username" -o tsv)
REGISTRY_PASSWORD=$(az acr credential show --name "${REGISTRY_NAME}" --query "passwords[0].value" -o tsv)

# -- Ensure Container Apps environment exists --
echo "==> Ensuring Container Apps environment exists..."
az containerapp env create \
    --name "${ENVIRONMENT_NAME}" \
    --resource-group "${RESOURCE_GROUP}" \
    --location "${LOCATION}" \
    --output none 2>/dev/null || true

# -- Build env vars array --
ENV_VARS=(
    "INTERNAL_TEAM_UTIL_SLACK_BOT_TOKEN=${INTERNAL_TEAM_UTIL_SLACK_BOT_TOKEN}"
    "INTERNAL_TEAM_UTIL_SLACK_APP_TOKEN=${INTERNAL_TEAM_UTIL_SLACK_APP_TOKEN}"
    "INTERNAL_TEAM_UTIL_USERS_JSON=${INTERNAL_TEAM_UTIL_USERS_JSON}"
    "INTERNAL_TEAM_UTIL_PING_LEAD_TIME_MINUTES=${INTERNAL_TEAM_UTIL_PING_LEAD_TIME_MINUTES:-5}"
    "INTERNAL_TEAM_UTIL_PING_INTERVAL_SECONDS=${INTERNAL_TEAM_UTIL_PING_INTERVAL_SECONDS:-60}"
    "INTERNAL_TEAM_UTIL_POLL_INTERVAL_SECONDS=${INTERNAL_TEAM_UTIL_POLL_INTERVAL_SECONDS:-30}"
    "INTERNAL_TEAM_UTIL_LOOKAHEAD_MINUTES=${INTERNAL_TEAM_UTIL_LOOKAHEAD_MINUTES:-15}"
)

# -- Deploy or update the container app --
echo "==> Deploying container app..."
az containerapp create \
    --name "${APP_NAME}" \
    --resource-group "${RESOURCE_GROUP}" \
    --environment "${ENVIRONMENT_NAME}" \
    --image "${IMAGE}" \
    --registry-server "${REGISTRY_SERVER}" \
    --registry-username "${REGISTRY_USERNAME}" \
    --registry-password "${REGISTRY_PASSWORD}" \
    --cpu 0.25 \
    --memory 0.5Gi \
    --min-replicas 1 \
    --max-replicas 1 \
    --ingress none \
    --env-vars "${ENV_VARS[@]}" \
    --output none 2>/dev/null || \
az containerapp update \
    --name "${APP_NAME}" \
    --resource-group "${RESOURCE_GROUP}" \
    --image "${IMAGE}" \
    --min-replicas 1 \
    --max-replicas 1 \
    --set-env-vars "${ENV_VARS[@]}" \
    --output none

echo "==> Deployed successfully."
az containerapp show \
    --name "${APP_NAME}" \
    --resource-group "${RESOURCE_GROUP}" \
    --query "properties.runningStatus" \
    -o tsv
