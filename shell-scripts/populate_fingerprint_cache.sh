#!/usr/bin/env bash
set -euo pipefail

# Populate fingerprint→profile_id cache in Redis DB 2
# Cron: */5 * * * *

echo "--- Fingerprint cache population started at $(date) ---"

python -m data_workers.scripts.populate_fingerprint_cache

echo "--- Fingerprint cache population completed at $(date) ---"
