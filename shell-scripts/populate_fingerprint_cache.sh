#!/usr/bin/env bash
set -euo pipefail

# Populate fingerprint→profile_id cache in Redis DB 2
# Cron: */5 * * * *

PROJECT_ROOT="/build/leo-activation/c720-data-activation"
cd "$PROJECT_ROOT"

echo "--- Fingerprint cache population started at $(date) ---"

/usr/bin/docker compose run -T --rm api python -m data_workers.scripts.populate_fingerprint_cache

echo "--- Fingerprint cache population completed at $(date) ---"
