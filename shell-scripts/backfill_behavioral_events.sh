#!/usr/bin/env bash
set -euo pipefail

# One-time backfill: syncs last 90 days of ticker events into behavioral_events.
# Do NOT run this hourly — use sync_and_score_hourly.sh for incremental updates.

echo "--- Starting behavioral_events backfill (last 90 days) at $(date) ---"
python -m data_workers.scripts.sync_behavioral_events
echo "--- Backfill complete at $(date) ---"
