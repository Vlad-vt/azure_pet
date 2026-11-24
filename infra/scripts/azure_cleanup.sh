#!/usr/bin/env bash
# Stage 0: delete ALL resource groups in the Azure for Students subscription and purge
# soft-deleted Key Vaults / Cognitive Services accounts. Destructive — asks for confirmation
# unless CONFIRM=yes.
source "$(dirname "$0")/common.sh"
require_students_subscription

echo "== Resource groups =="
az group list --query "[].{name:name, location:location, state:properties.provisioningState}" -o table
mapfile -t groups < <(az group list --query "[].name" -o tsv)
echo "== Resources =="
az resource list --query "[].{name:name, type:type, rg:resourceGroup}" -o table

if [[ ${#groups[@]} -gt 0 ]]; then
  if [[ "${CONFIRM:-}" != "yes" ]]; then
    read -r -p "Delete ${#groups[@]} resource group(s): ${groups[*]} ? [yes/N] " answer
    [[ "$answer" == "yes" ]] || { echo "aborted"; exit 1; }
  fi
  for g in "${groups[@]}"; do
    echo "deleting $g (no-wait)"; az group delete -n "$g" --yes --no-wait
  done
  for g in "${groups[@]}"; do az group wait -n "$g" --deleted 2>/dev/null || true; done
fi

echo "== Purging soft-deleted Key Vaults =="
for kv in $(az keyvault list-deleted --query "[].name" -o tsv 2>/dev/null); do
  echo "purge keyvault $kv"; az keyvault purge -n "$kv" || true
done
echo "== Purging soft-deleted Cognitive Services accounts =="
az cognitiveservices account list-deleted --query "[].{n:name,l:location,id:id}" -o tsv 2>/dev/null |
while read -r name loc id; do
  rg=$(sed -n 's#.*/resourceGroups/\([^/]*\)/.*#\1#p' <<<"$id")
  echo "purge cognitive $name"; az cognitiveservices account purge -n "$name" -l "$loc" -g "$rg" || true
done
echo "remaining resource groups:"; az group list -o table
