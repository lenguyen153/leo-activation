#!/usr/bin/env bash
set -euo pipefail

# ============================================================
# Abandoned Cart Campaign — hourly
# ============================================================
# Run manually:
#   cd /build/prod-app && docker run --rm --env-file .env \
#     --network prod-app_default \
#     registry.innotech.vn/cdp-ai/c720-data-activation/core:latest \
#     bash shell-scripts/run_abandoned_cart.sh
#
# Crontab (host, :10 of every hour, offset from other cron jobs):
#   10 * * * *  cd /build/prod-app && docker run --rm --env-file .env \
#     --network prod-app_default \
#     registry.innotech.vn/cdp-ai/c720-data-activation/core:latest \
#     bash shell-scripts/run_abandoned_cart.sh >> /var/log/abandoned_cart.log 2>&1
#
# Prerequisites: shell-scripts/poll_market_snapshot.sh must be running
# every 15 min so market_snapshot_history has price data to compare against.
# ============================================================

echo "--- Abandoned Cart Campaign started at $(date) ---"

echo "--- Step 1: Compute abandoned tickers per profile ---"
python -m data_workers.scripts.compute_abandoned_cart

echo "--- Step 2: Run campaign engine (dispatches per-ticker push) ---"
python -m data_workers.campaign_engine.engine

echo "--- Abandoned Cart Campaign finished at $(date) ---"
