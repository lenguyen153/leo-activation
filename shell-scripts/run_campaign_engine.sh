#!/usr/bin/env bash
set -euo pipefail

# ============================================================
# Rule-Based Notification Campaign Engine — Hourly Runner
# ============================================================
# Crontab entry (runs every hour on the hour):
#   0 * * * * cd /path/to/leo-activation && bash shell-scripts/run_campaign_engine.sh >> /var/log/campaign_engine.log 2>&1
# ============================================================

echo "--- Campaign Engine started at $(date) ---"

echo "--- Step 1: Pre-compute activity drop metrics ---"
python -m data_workers.scripts.compute_activity_drop

echo "--- Step 2: Running campaign engine ---"
python -m data_workers.campaign_engine.engine

echo "--- Campaign Engine finished at $(date) ---"
