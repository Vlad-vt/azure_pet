#!/usr/bin/env bash
# Stage 6: passwordless GitHub Actions -> Azure (OIDC federated credentials).
# Creates an Entra app + service principal scoped to the resource group (Contributor only),
# federated credentials for `main` and the `production` environment, then stores IDs as GitHub
# secrets and resource names as GitHub variables. Run on a workstation with `az` and `gh` logged in.
source "$(dirname "$0")/common.sh"
require_students_subscription
REPO="${REPO:-Vlad-vt/azure_pet}"
APP_NAME="${APP_NAME:-gh-oidc-skumatch}"

sub_id=$(az account show --query id -o tsv)
tenant_id=$(az account show --query tenantId -o tsv)
rg_id=$(az group show -n "$RG" --query id -o tsv)

app_id=$(az ad app list --display-name "$APP_NAME" --query "[0].appId" -o tsv)
if [[ -z "$app_id" ]]; then
  app_id=$(az ad app create --display-name "$APP_NAME" --query appId -o tsv)
fi
az ad sp show --id "$app_id" -o none 2>/dev/null || az ad sp create --id "$app_id" -o none

for subject in "repo:${REPO}:ref:refs/heads/main" "repo:${REPO}:environment:production"; do
  name=$(echo "$subject" | tr ':/' '--' | cut -c1-120)
  if ! az ad app federated-credential list --id "$app_id" --query "[?subject=='$subject']" -o tsv | grep -q .; then
    az ad app federated-credential create --id "$app_id" --parameters "{
      \"name\": \"$name\", \"issuer\": \"https://token.actions.githubusercontent.com\",
      \"subject\": \"$subject\", \"audiences\": [\"api://AzureADTokenExchange\"]}" -o none
  fi
done

# Least privilege: Contributor on the project resource group only.
az role assignment create --assignee "$app_id" --role Contributor --scope "$rg_id" -o none 2>/dev/null || true

gh secret set AZURE_CLIENT_ID --repo "$REPO" --body "$app_id"
gh secret set AZURE_TENANT_ID --repo "$REPO" --body "$tenant_id"
gh secret set AZURE_SUBSCRIPTION_ID --repo "$REPO" --body "$sub_id"

outputs="$STATE_DIR/outputs.json"
val() { python3 -c "import json,sys;print(json.load(open('$outputs'))['$1']['value'])"; }
gh variable set AZURE_RG --repo "$REPO" --body "$RG"
gh variable set ACA_APP --repo "$REPO" --body "$(val appName)"
gh variable set ACA_MIGRATE_JOB --repo "$REPO" --body "$(val migrateJobName)"
gh variable set ACA_INGEST_JOB --repo "$REPO" --body "$(val ingestJobName)"
gh variable set PG_SERVER --repo "$REPO" --body "$(val pgServerName)"
echo "OIDC configured for $REPO (IDs stored as GitHub secrets, not printed)."
