"""
Centralized logging configuration for all cron job entry-points.

Usage
-----
In every script's entry-point (module level or __main__ block):

    from data_utils.logging_config import configure_logging, get_logger, log_event

    configure_logging()          # call once per process
    logger = get_logger(__name__)

    # Verbose progress (suppressed in production):
    logger.info("Fetched %d events", n)

    # Final result (always visible, even in production):
    log_event(logger, "my_job_complete", inserted=500, failed=12, duration_ms=1450)

.env variable
-------------
LOG_GRANULARITY=verbose      # verbose | production  (default: verbose)

  verbose    — INFO level; all progress + summary logs
  production — SUMMARY level (25); only final-result events, warnings, and errors
"""

import json
import logging
import os

# ---------------------------------------------------------------------------
# Custom level: SUMMARY (25) sits between INFO (20) and WARNING (30).
# In production mode the root logger is set to SUMMARY, which passes
# SUMMARY + WARNING + ERROR + CRITICAL but suppresses DEBUG + INFO.
# ---------------------------------------------------------------------------
SUMMARY: int = 25
logging.addLevelName(SUMMARY, "SUMMARY")


class JsonFormatter(logging.Formatter):
    """Emit every log record as a single-line JSON object."""

    def format(self, record: logging.LogRecord) -> str:
        payload: dict = {
            "ts": self.formatTime(record, "%Y-%m-%dT%H:%M:%S"),
            "level": record.levelname,
            "logger": record.name,
            "event": record.getMessage(),
        }
        if record.exc_info:
            payload["exc"] = self.formatException(record.exc_info)
        # Merge structured fields injected by log_event()
        payload.update(getattr(record, "_fields", {}))
        return json.dumps(payload, default=str)


def configure_logging() -> None:
    """
    Configure the root logger with a JSON formatter.
    Call once at the entry-point of each script/module main block.
    Replaces all per-file logging.basicConfig() calls.
    """
    granularity = os.getenv("LOG_GRANULARITY", "verbose").lower()
    level = SUMMARY if granularity == "production" else logging.INFO

    handler = logging.StreamHandler()
    handler.setFormatter(JsonFormatter())

    root = logging.getLogger()
    root.handlers = []
    root.addHandler(handler)
    root.setLevel(level)


def get_logger(name: str) -> logging.Logger:
    """Drop-in replacement for logging.getLogger(name)."""
    return logging.getLogger(name)


def log_event(logger: logging.Logger, event: str, **fields) -> None:
    """
    Emit a SUMMARY-level structured log event.

    These events are always visible in production mode (LOG_GRANULARITY=production)
    because SUMMARY (25) > INFO (20). Use them for final results with counts/metrics.

    Example:
        log_event(logger, "sync_complete", inserted=500, failed=12, duration_ms=1450)
    """
    if not logger.isEnabledFor(SUMMARY):
        return
    record = logger.makeRecord(
        logger.name, SUMMARY, "(log_event)", 0, event, (), None
    )
    record._fields = fields  # type: ignore[attr-defined]
    logger.handle(record)
