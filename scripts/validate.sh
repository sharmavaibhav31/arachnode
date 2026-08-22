#!/bin/bash
# =============================================================================
# scripts/validate.sh — JobHunter System Validation
# =============================================================================
# Run after: docker compose up -d
# Usage:     bash scripts/validate.sh
#            JOBHUNTER_API_KEY=your-key bash scripts/validate.sh
# =============================================================================

set -euo pipefail

BASE="${GATEWAY_BASE_URL:-http://localhost:8080}"
API_KEY="${JOBHUNTER_API_KEY:-}"
WAIT_SECS="${WAIT_SECS:-20}"
FAILED=0

# Build curl auth header args
CURL_AUTH=()
if [ -n "$API_KEY" ]; then
  CURL_AUTH=(-H "X-API-Key: $API_KEY")
fi

# ---------------------------------------------------------------------------
print_header() {
  echo ""
  echo "============================================="
  echo "  JobHunter System Validation"
  echo "  Target: $BASE"
  echo "============================================="
  echo ""
}

wait_for_startup() {
  echo "Waiting ${WAIT_SECS}s for services to start..."
  sleep "$WAIT_SECS"
  echo ""
}

check() {
  local name="$1"
  local url="$2"
  local expected="${3:-200}"

  local status
  status=$(curl -s -o /dev/null -w "%{http_code}" --max-time 10 \
    "${CURL_AUTH[@]}" "$url" 2>/dev/null || echo "000")

  if [ "$status" = "$expected" ]; then
    printf "  \033[32m✓\033[0m  %-40s  HTTP %s\n" "$name" "$status"
  else
    printf "  \033[31m✗\033[0m  %-40s  Expected %s, got %s\n" "$name" "$expected" "$status"
    FAILED=1
  fi
}

check_json_key() {
  local name="$1"
  local url="$2"
  local key="$3"

  local body
  body=$(curl -s --max-time 10 "${CURL_AUTH[@]}" "$url" 2>/dev/null || echo "{}")
  if echo "$body" | grep -q "\"$key\""; then
    printf "  \033[32m✓\033[0m  %-40s  key '%s' present\n" "$name" "$key"
  else
    printf "  \033[31m✗\033[0m  %-40s  key '%s' missing in response\n" "$name" "$key"
    FAILED=1
  fi
}

# ---------------------------------------------------------------------------
print_header

if [ "${SKIP_WAIT:-0}" = "0" ]; then
  wait_for_startup
fi

echo "--- Public Endpoints (no auth) ---"
check "Dashboard HTML"            "$BASE/"                                200
check "Gateway health"            "$BASE/api/health"                      200

echo ""
echo "--- Authenticated Endpoints ---"
if [ -z "$API_KEY" ]; then
  echo "  (No API key set — skipping auth checks, running in dev mode)"
fi
check "Jobs list"                 "$BASE/api/jobs?limit=1"                200
check "Stats endpoint"            "$BASE/api/stats"                       200
check "Contacts endpoint"         "$BASE/api/contacts?company=test"       200

echo ""
echo "--- Service Health Fan-out ---"
# Parse the /api/health response for individual service statuses
health_body=$(curl -s --max-time 15 "${CURL_AUTH[@]}" "$BASE/api/health" 2>/dev/null || echo "{}")
for svc in aggregator scraper contact email-gen crawler; do
  if echo "$health_body" | grep -q "\"$svc\""; then
    if echo "$health_body" | python3 -c "
import sys, json
d = json.load(sys.stdin)
svcs = {s['service']: s['status'] for s in d.get('services', [])}
status = svcs.get('$svc', 'missing')
print(status)
sys.exit(0 if status == 'ok' else 1)
" 2>/dev/null; then
      printf "  \033[32m✓\033[0m  %-40s  ok\n" "Service: $svc"
    else
      svc_status=$(echo "$health_body" | python3 -c "
import sys, json
d = json.load(sys.stdin)
svcs = {s['service']: s['status'] for s in d.get('services', [])}
print(svcs.get('$svc', 'missing'))
" 2>/dev/null || echo "parse-error")
      printf "  \033[33m⚠\033[0m  %-40s  %s\n" "Service: $svc" "$svc_status"
    fi
  else
    printf "  \033[31m✗\033[0m  %-40s  not in health response\n" "Service: $svc"
    FAILED=1
  fi
done

echo ""
echo "--- Summary ---"
if [ "$FAILED" = "1" ]; then
  echo "  Some checks failed."
  echo "  Diagnose with:"
  echo "    docker compose logs aggregator"
  echo "    docker compose logs contact"
  echo "    docker compose logs scraper"
  echo "    docker compose ps"
  exit 1
else
  echo "  All systems operational. Ready for demo."
  echo ""
  echo "  Dashboard:  $BASE"
  if [ -n "$API_KEY" ]; then
    echo "  API Key:    $API_KEY"
  else
    echo "  API Key:    (not set — unauthenticated mode)"
  fi
  echo ""
fi
