"""
Batch scoring reconciliation — re-scores last 6h window as CDC failsafe.
Runs GC, batch scoring, and NBA update.
Intended to run every 6 hours via cron.
"""

from datetime import datetime, timedelta, timezone

from agentic_tools.recommendation_system.interest_score import (
    run_batch_scoring_job,
    run_garbage_collection,
)
from agentic_tools.recommendation_orchestrator import run_batch_nba_update
from data_utils.logging_config import configure_logging, get_logger, log_event
from data_utils.settings import DatabaseSettings

configure_logging()
logger = get_logger(__name__)


def main():
    settings = DatabaseSettings()

    # 1. GC stale rows
    run_garbage_collection(settings)

    # 2. Score window: last 6 hours
    now = datetime.now(timezone.utc)
    window_end = now.replace(minute=0, second=0, microsecond=0)
    window_start = window_end - timedelta(hours=6)

    logger.info("Scoring window: %s -> %s", window_start.isoformat(), window_end.isoformat())
    run_batch_scoring_job(settings, window_start.isoformat(), window_end.isoformat())

    # 3. NBA update
    run_batch_nba_update(settings)
    log_event(logger, "batch_scoring_reconciliation_complete",
              window_start=window_start.isoformat(), window_end=window_end.isoformat())


if __name__ == "__main__":
    main()
