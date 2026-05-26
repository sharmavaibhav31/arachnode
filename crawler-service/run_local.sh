#!/usr/bin/env bash
# run_local.sh — run a spider directly without Docker.
# Requires: Redis running on localhost:6379
#           Python venv with requirements.txt installed
#           playwright install chromium (once)

set -e

SPIDER="${1:-remotive}"
ROLE="${JOBSEEKER_ROLE:-Backend Engineer}"
STACK="${JOBSEEKER_STACK:-Python,Go,FastAPI,PostgreSQL,Kubernetes}"

echo "=================================================="
echo " Arachnode Crawler"
echo " Spider : $SPIDER"
echo " Role   : $ROLE"
echo " Stack  : $STACK"
echo "=================================================="
echo ""

export JOBSEEKER_ROLE="$ROLE"
export JOBSEEKER_STACK="$STACK"

scrapy crawl "$SPIDER" \
  -s JOBSEEKER_ROLE="$ROLE" \
  -s JOBSEEKER_STACK="$STACK" \
  -s LOG_LEVEL=INFO

echo ""
echo "Done. Run 'python read_stream.py --count 20' to see what was emitted."
