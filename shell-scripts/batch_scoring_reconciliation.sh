#!/usr/bin/env bash
set -euo pipefail

# Batch scoring reconciliation — re-scores last 6h window as CDC failsafe
# Cron: 0 */6 * * *

PROJECT_ROOT="/build/leo-activation/c720-data-activation"
cd "$PROJECT_ROOT"

echo "--- Batch scoring reconciliation started at $(date) ---"

/usr/bin/docker compose run -T --rm api python -m data_workers.scripts.batch_scoring_reconciliation

echo "--- Batch scoring reconciliation completed at $(date) ---"
