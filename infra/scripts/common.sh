#!/usr/bin/env bash
# Shared helpers. Never prints secrets or subscription/tenant IDs.
set -euo pipefail

: "${LOCATION:=germanywestcentral}"
: "${RG:=rg-skumatch}"
: "${NAME_PREFIX:=skumatch}"
# shellcheck disable=SC2034  # used by the scripts that source this file
STATE_DIR="${SKUMATCH_STATE_DIR:-$HOME/.skumatch}"   # local, outside the repo (chmod 700)

require_students_subscription() {
  local offer name
  name=$(az account show --query name -o tsv)
  offer=$(az account show --query "user.type" -o tsv)
  echo "Active subscription: ${name} (login type: ${offer})"
  if [[ "${name}" != *"Students"* ]]; then
    echo "ERROR: active subscription is not 'Azure for Students' — refusing to continue." >&2
    exit 1
  fi
}
