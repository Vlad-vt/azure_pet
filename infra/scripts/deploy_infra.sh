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

echo "Checking Standard_B1ms availability in ${LOCATION}..."
if ! az postgres flexible-server list-skus -l "$LOCATION" \
     --query "[].supportedServerEditions[?name=='Burstable'][].supportedServerSkus[].name" -o tsv \
     | grep -qx "Standard_B1ms"; then
  echo "ERROR: Standard_B1ms not offered in ${LOCATION}; try swedencentral, polandcentral or northeurope." >&2
  exit 1
fi

mkdir -p "$STATE_DIR" && chmod 700 "$STATE_DIR"
pw_file="$STATE_DIR/pg_admin_password"
if [[ ! -s "$pw_file" ]]; then
  # URL-safe, 40 chars; stored only on this machine — copy it to a password manager.
  python3 -c "import secrets,string;a=string.ascii_letters+string.digits;print(''.join(secrets.choice(a) for _ in range(40)))" > "$pw_file"
  chmod 600 "$pw_file"
  echo "Generated PostgreSQL admin password -> $pw_file"
fi

az group create -n "$RG" -l "$LOCATION" --tags project=skumatch cost-center=portfolio -o none
az deployment group create -g "$RG" -n "skumatch-$(date +%Y%m%d%H%M%S)" \
  --template-file "$(dirname "$0")/../bicep/main.bicep" \
  --parameters namePrefix="$NAME_PREFIX" image="$IMAGE" \
               pgAdminPassword=@"$pw_file" \
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
