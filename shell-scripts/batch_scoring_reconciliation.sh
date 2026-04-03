#!/usr/bin/env bash
set -euo pipefail

# Batch scoring reconciliation — re-scores last 6h window as CDC failsafe
# Cron: 0 */6 * * *

echo "--- Batch scoring reconciliation started at $(date) ---"

python -m data_workers.scripts.batch_scoring_reconciliation

echo "--- Batch scoring reconciliation completed at $(date) ---"
