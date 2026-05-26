#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

POSTGRES_SERVICE="${POSTGRES_SERVICE:-postgres}"
REDIS_SERVICE="${REDIS_SERVICE:-redis}"
POSTGRES_USER="${POSTGRES_USER:-jobuser}"
POSTGRES_DB="${POSTGRES_DB:-jobsdb}"

ASSUME_YES=0
RESTART_STACK=1

usage() {
  cat <<'EOF'
Usage: scripts/reset.sh [--yes] [--no-restart]

Safely reset local Arachnode development state.

Options:
  -y, --yes       Skip the confirmation prompt.
  --no-restart    Reset Postgres/Redis state but do not restart the full stack.
  -h, --help      Show this help message.

This script is intentionally scoped:
  - truncates Arachnode tables if they exist: emails, contacts, jobs
  - deletes Arachnode Redis keys: jobs:raw, dedup:*, dedup:agg:*
  - does not run docker compose down -v
  - does not run Redis FLUSHALL
EOF
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    -y|--yes)
      ASSUME_YES=1
      shift
      ;;
    --no-restart)
      RESTART_STACK=0
      shift
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      echo "Unknown option: $1" >&2
      usage
      exit 2
      ;;
  esac
done

if docker compose version >/dev/null 2>&1; then
  COMPOSE=(docker compose)
elif command -v docker-compose >/dev/null 2>&1; then
  COMPOSE=(docker-compose)
else
  echo "Docker Compose is required. Install Docker Compose v2 or docker-compose." >&2
  exit 1
fi

if [[ "$ASSUME_YES" -ne 1 ]]; then
  cat <<EOF
This will reset local Arachnode development state.

Postgres:
  - TRUNCATE emails, contacts, jobs if those tables exist

Redis:
  - DEL jobs:raw
  - DEL keys matching dedup:* and dedup:agg:*

Docker volumes and unrelated Redis keys are not removed.
EOF
  read -r -p "Continue? Type 'reset' to proceed: " CONFIRM
  if [[ "$CONFIRM" != "reset" ]]; then
    echo "Reset cancelled."
    exit 0
  fi
fi

echo "Stopping application services..."
"${COMPOSE[@]}" stop scheduler gateway email-gen contact scraper aggregator crawler >/dev/null 2>&1 || true

echo "Starting Postgres and Redis..."
"${COMPOSE[@]}" up -d "$POSTGRES_SERVICE" "$REDIS_SERVICE"

echo "Resetting Postgres tables..."
"${COMPOSE[@]}" exec -T "$POSTGRES_SERVICE" psql \
  -U "$POSTGRES_USER" \
  -d "$POSTGRES_DB" \
  -v ON_ERROR_STOP=1 <<'SQL'
DO $$
DECLARE
  tables_to_reset text[];
BEGIN
  SELECT array_agg(format('%I', table_name))
  INTO tables_to_reset
  FROM information_schema.tables
  WHERE table_schema = 'public'
    AND table_name IN ('emails', 'contacts', 'jobs');

  IF tables_to_reset IS NULL THEN
    RAISE NOTICE 'No Arachnode tables found to reset.';
  ELSE
    EXECUTE 'TRUNCATE TABLE ' || array_to_string(tables_to_reset, ', ') || ' RESTART IDENTITY CASCADE';
    RAISE NOTICE 'Reset tables: %', array_to_string(tables_to_reset, ', ');
  END IF;
END $$;
SQL

echo "Resetting Arachnode Redis keys..."
"${COMPOSE[@]}" exec -T "$REDIS_SERVICE" sh -c '
set -eu

delete_pattern() {
  pattern="$1"
  redis-cli --scan --pattern "$pattern" | while IFS= read -r key; do
    [ -n "$key" ] && redis-cli DEL "$key" >/dev/null
  done
}

redis-cli DEL jobs:raw >/dev/null
delete_pattern "dedup:*"
delete_pattern "dedup:agg:*"
'

if [[ "$RESTART_STACK" -eq 1 ]]; then
  echo "Restarting Arachnode stack..."
  "${COMPOSE[@]}" up -d --build
  echo "Clearing scheduler run summary if present..."
  "${COMPOSE[@]}" exec -T gateway sh -c 'rm -f /data/run_summary.json' >/dev/null 2>&1 || true
else
  echo "Skipping stack restart because --no-restart was provided."
  echo "Scheduler run summary is left untouched because gateway/scheduler are not restarted."
fi

echo "Local Arachnode development state has been reset."
