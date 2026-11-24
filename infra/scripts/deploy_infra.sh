#!/usr/bin/env bash
# Stage 5: idempotent infrastructure deployment (Bicep) + first catalog load.
#   IMAGE=ghcr.io/vlad-vt/azure_pet:<tag> infra/scripts/deploy_infra.sh
# Optional: GHCR_USERNAME / GHCR_TOKEN for private ghcr.io packages, LOCATION, RG.
source "$(dirname "$0")/common.sh"
require_students_subscription
: "${IMAGE:?set IMAGE=ghcr.io/<owner>/azure_pet:<tag>}"

for provider in Microsoft.App Microsoft.OperationalInsights Microsoft.DBforPostgreSQL; do
  az provider register -n "$provider" -o none
done

b1ms_available() {
  az postgres flexible-server list-skus -l "$1" \
    --query "[].supportedServerEditions[?name=='Burstable'][].supportedServerSkus[].name" -o tsv \
    2>/dev/null | grep -qx "Standard_B1ms"
}

# Reuse the region of an existing deployment; otherwise pick the first region that offers B1ms
# (this Azure for Students subscription: PostgreSQL is restricted in germanywestcentral and an
# "Allowed resource deployment regions" policy limits resources to 5 EU regions).
if existing=$(az group show -n "$RG" --query location -o tsv 2>/dev/null); then
  LOCATION="$existing"
else
  # Candidates are the regions allowed by the subscription policy that also offer ACA + B1ms.
  for candidate in "$LOCATION" belgiumcentral norwayeast switzerlandnorth; do
    if b1ms_available "$candidate"; then LOCATION="$candidate"; break; fi
    echo "Standard_B1ms not offered in $candidate for this subscription"
  done
fi
b1ms_available "${PG_LOCATION:-$LOCATION}" || { echo "ERROR: no region with Standard_B1ms found" >&2; exit 1; }
echo "Region: $LOCATION (PostgreSQL: ${PG_LOCATION:-$LOCATION})"

mkdir -p "$STATE_DIR" && chmod 700 "$STATE_DIR"
pw_file="$STATE_DIR/pg_admin_password"
app="${NAME_PREFIX}-api"
if [[ ! -s "$pw_file" ]] && az containerapp show -g "$RG" -n "$app" -o none 2>/dev/null; then
  # Re-deploy from a new machine: recover the password from the Container Apps secret so the
  # server password is not rotated by accident.
  az containerapp secret show -g "$RG" -n "$app" --secret-name database-url --query value -o tsv |
    python3 -c "import sys,urllib.parse as u;print(u.unquote(u.urlsplit(sys.stdin.read().strip()).password))" \
    > "$pw_file"
  chmod 600 "$pw_file"
  echo "Recovered PostgreSQL admin password from the Container App secret -> $pw_file"
fi
if [[ ! -s "$pw_file" ]]; then
  # URL-safe, 40 chars; stored only on this machine and in the Container Apps secret.
  python3 -c "import secrets,string;a=string.ascii_letters+string.digits;print(''.join(secrets.choice(a) for _ in range(40)))" > "$pw_file"
  chmod 600 "$pw_file"
  echo "Generated PostgreSQL admin password -> $pw_file"
fi
PG_PASSWORD="$(cat "$pw_file")"

az group create -n "$RG" -l "$LOCATION" --tags project=skumatch cost-center=portfolio -o none
az deployment group create -g "$RG" -n "skumatch-$(date +%Y%m%d%H%M%S)" \
  --template-file "$(dirname "$0")/../bicep/main.bicep" \
  --parameters namePrefix="$NAME_PREFIX" image="$IMAGE" pgLocation="${PG_LOCATION:-$LOCATION}" \
               pgAdminPassword="$PG_PASSWORD" \
               ghcrUsername="${GHCR_USERNAME:-}" ghcrToken="${GHCR_TOKEN:-}" \
  --query "properties.outputs" -o json > "$STATE_DIR/outputs.json"
python3 - "$STATE_DIR/outputs.json" <<'PY'
import json, sys
out = json.load(open(sys.argv[1]))
for k, v in out.items():
    print(f"{k:18} {v['value']}")
PY

if [[ "${SKIP_DATA:-}" != "1" ]]; then
  for job in migrate ingest; do
    name="${NAME_PREFIX}-${job}"
    exec_name=$(az containerapp job start -g "$RG" -n "$name" --query name -o tsv)
    echo "started $name ($exec_name)"
    for _ in $(seq 1 120); do
      status=$(az containerapp job execution show -g "$RG" -n "$name" --job-execution-name "$exec_name" --query properties.status -o tsv)
      [[ "$status" == "Succeeded" ]] && { echo "$name: Succeeded"; break; }
      [[ "$status" == "Failed" ]] && { echo "$name: FAILED" >&2; exit 1; }
      sleep 10
    done
  done
fi
