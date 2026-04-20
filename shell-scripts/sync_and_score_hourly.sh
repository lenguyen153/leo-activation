#!/usr/bin/env bash
set -euo pipefail

SEGMENT_ID="6D8sWO4mkAQgwPV02vzzqi"

echo "--- Starting scheduled job for segment $SEGMENT_ID at $(date) ---"

echo "--- Step 1: Syncing profile ---"
python -m data_workers.scripts.sync_profile "$SEGMENT_ID"

echo "--- Step 2: Backfilling primary email from identities ---"
python -m data_workers.scripts.backfill_primary_email

echo "--- Step 3: Syncing active users portfolios ---"
python -m data_workers.sync.sync_active_users_portfolios

echo "--- Step 4: Running interest score calculation ---"
python -m agentic_tools.recommendation_system.interest_score

echo "--- Step 5: Running recommendation orchestrator (NBA/NLA upsert) ---"
python -m agentic_tools.recommendation_orchestrator

echo "--- Job Complete at $(date) ---"