#!/usr/bin/env bash
set -euo pipefail

# ============================================================
# Market Snapshot Poller — every 15 min
# ============================================================
# Run manually:
#   cd /build/prod-app && docker run --rm --env-file .env \
#     --network prod-app_default \
#     registry.innotech.vn/cdp-ai/c720-data-activation/core:latest \
#     bash shell-scripts/poll_market_snapshot.sh
#
# Crontab (host):
#   */15 * * * *  cd /build/prod-app && docker run --rm --env-file .env \
#     --network prod-app_default \
#     registry.innotech.vn/cdp-ai/c720-data-activation/core:latest \
#     bash shell-scripts/poll_market_snapshot.sh >> /var/log/market_snapshot.log 2>&1
# ============================================================

echo "--- Market Snapshot Poll started at $(date) ---"
python -m data_workers.scripts.poll_market_snapshot
echo "--- Market Snapshot Poll finished at $(date) ---"
