#!/usr/bin/env bash
# sim_backtest.sh — replay a fixed allocation strategy month-by-month
#
# Usage:
#   ./scripts/sim_backtest.sh [START] [END] [WEIGHTS_JSON]
#
# Examples:
#   ./scripts/sim_backtest.sh 2024-01-01 2024-12-01
#   ./scripts/sim_backtest.sh 2023-01-01 2025-01-01 '{"SPY":0.5,"QQQ":0.3,"GLD":0.2}'
#
# Env vars:
#   WEBHOOK_URL     defaults to http://localhost:5000/webhook
#   WEBHOOK_SECRET  set if your server has auth enabled
#
# Prerequisites:
#   - Backend running with TIPORTFOLIO_MODE=simulated  (make dev)
#   - python3 available on PATH

set -euo pipefail

START="${1:-2024-01-01}"
END="${2:-2024-12-01}"
WEIGHTS="${3:-{\"SPY\":0.6,\"QQQ\":0.4}}"
URL="${WEBHOOK_URL:-http://localhost:5000/webhook}"
TOKEN="${WEBHOOK_SECRET:-}"

# Validate python3 is available
if ! command -v python3 &>/dev/null; then
  echo "Error: python3 is required." >&2
  exit 1
fi

# Generate first-of-month dates between START and END (inclusive)
DATES=$(python3 - "$START" "$END" <<'PYEOF'
import sys
from datetime import date

start = date.fromisoformat(sys.argv[1]).replace(day=1)
end   = date.fromisoformat(sys.argv[2]).replace(day=1)

d = start
while d <= end:
    print(d.isoformat())
    m, y = d.month + 1, d.year
    if m > 12:
        m, y = 1, y + 1
    d = d.replace(year=y, month=m, day=1)
PYEOF
)

TOTAL=$(echo "$DATES" | wc -l | tr -d ' ')

echo "sim_backtest: $START → $END  ($TOTAL months)"
echo "weights : $WEIGHTS"
echo "url     : $URL"
echo "──────────────────────────────────────────────"

SUCCESS=0
FAILED=0

for d in $DATES; do
  PAYLOAD=$(python3 -c "
import json, sys
weights = json.loads(sys.argv[1])
print(json.dumps({'weights': weights, 'date': sys.argv[2]}))
" "$WEIGHTS" "$d")

  CURL_ARGS=(-s --connect-timeout 5 --max-time 30 -w '\n%{http_code}' -X POST "$URL" \
    -H "Content-Type: application/json" \
    -d "$PAYLOAD")

  if [ -n "$TOKEN" ]; then
    CURL_ARGS+=(-H "Authorization: Bearer $TOKEN")
  fi

  RAW=$(curl "${CURL_ARGS[@]}" 2>/dev/null || printf '{"error":"connection refused"}\n000')
  HTTP_CODE=$(echo "$RAW" | tail -1)
  BODY=$(echo "$RAW" | sed '$d')

  STATUS=$(python3 -c "
import json, sys
try:
    d = json.loads(sys.stdin.read())
    print(d.get('status', d.get('error', '?')))
except Exception:
    print('parse_error')
" <<< "$BODY" 2>/dev/null || echo "?")

  EVENT_ID=$(python3 -c "
import json, sys
try:
    d = json.loads(sys.stdin.read())
    print(d.get('rebalance_event', {}).get('id', '-'))
except Exception:
    print('-')
" <<< "$BODY" 2>/dev/null || echo "-")

  if [ "$HTTP_CODE" = "202" ]; then
    echo "  $d  ✓  status=$STATUS  event_id=$EVENT_ID"
    SUCCESS=$((SUCCESS + 1))
  else
    echo "  $d  ✗  http=$HTTP_CODE  $STATUS"
    FAILED=$((FAILED + 1))
  fi
done

echo "──────────────────────────────────────────────"
echo "Done: $SUCCESS succeeded, $FAILED failed"
echo ""
echo "View chart : http://localhost:5173"
echo "Reset data : make reset"
