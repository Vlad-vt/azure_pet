#!/usr/bin/env bash
# Monthly cost budget with e-mail alerts at $5 / $15 / $30 (actual spend).
# Azure for Students subscriptions may reject Cost Management budgets via API (offer
# MS-AZR-0170P); the script then prints the manual portal checklist from HANDOFF.md.
source "$(dirname "$0")/common.sh"
require_students_subscription
: "${ALERT_EMAIL:?set ALERT_EMAIL=you@example.com}"
sub_id=$(az account show --query id -o tsv)
start=$(date -u +%Y-%m-01)
end=$(date -u -d "+2 years" +%Y-%m-01)

body=$(python3 - "$ALERT_EMAIL" "$start" "$end" <<'PY'
import json, sys
email, start, end = sys.argv[1:]
notes = {
    f"actual_{amount}": {
        "enabled": True, "operator": "GreaterThanOrEqualTo",
        "threshold": amount / 30 * 100,  # percent of the $30 budget
        "thresholdType": "Actual", "contactEmails": [email],
    }
    for amount in (5, 15, 30)
}
print(json.dumps({"properties": {
    "category": "Cost", "amount": 30, "timeGrain": "Monthly",
    "timePeriod": {"startDate": f"{start}T00:00:00Z", "endDate": f"{end}T00:00:00Z"},
    "notifications": notes}}))
PY
)
if az rest --method put \
     --url "https://management.azure.com/subscriptions/${sub_id}/providers/Microsoft.Consumption/budgets/skumatch-monthly?api-version=2023-11-01" \
     --body "$body" -o none; then
  echo "Budget 'skumatch-monthly' created: alerts at \$5 / \$15 / \$30."
else
  echo "Budget API rejected for this subscription type — follow the manual checklist in HANDOFF.md." >&2
  exit 2
fi
