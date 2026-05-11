"""
Backfill behavioral_events from ArangoDB cdp_trackingevent (last 3 months).

Maps each event that has instrument_id / instrument_id_list to a row in behavioral_events:
  entity_type     = 'ticker'
  entity_id       = instrument_id
  sentiment_val   = metric.score (integer points from cdp_eventmetric)
  meta_data       = event.eventData

event_id is a deterministic SHA-256 hash of (event._key, ticker).
To make this script fully idempotent on re-runs, add a unique index first:
  CREATE UNIQUE INDEX ON behavioral_events (event_id);
Then the INSERT ON CONFLICT DO NOTHING below will guard against duplicates.
"""

import datetime
import hashlib
import json
import os

from data_utils.logging_config import configure_logging, get_logger, log_event
from data_utils.settings import DatabaseSettings

configure_logging()
logger = get_logger("data_workers.scripts.sync_behavioral_events")

TARGET_TENANT = os.getenv("TARGET_TENANT", "master")

_ARANGO_QUERY = """
FOR event IN cdp_trackingevent
    FILTER event.createdAt >= @start_time
    FILTER event.createdAt < @end_time

    LET single = event.eventData.instrument_id
    LET list   = event.eventData.instrument_id_list
    LET tickers = (
        single != null AND single != ""
        ? [single]
        : (IS_ARRAY(list) AND LENGTH(list) > 0 ? list : [])
    )
    FILTER LENGTH(tickers) > 0

    FOR ticker IN tickers
        FILTER ticker != null AND ticker != ""

        FOR profile IN cdp_profile
            FILTER profile.fingerprintId == event.fingerprintId

            FOR metric IN cdp_eventmetric
                FILTER metric.eventName == event.metricName

                RETURN {
                    "event_key":         event._key,
                    "profile_id":        profile._key,
                    "event_metric_name": event.metricName,
                    "ticker":            ticker,
                    "points":            metric.score,
                    "event_data":        event.eventData,
                    "created_at":        event.createdAt
                }
"""

_INSERT_SQL = """
    INSERT INTO behavioral_events (
        event_id, tenant_id, profile_id,
        event_metric_name,
        entity_type, entity_id,
        sentiment_val, meta_data, created_at
    ) VALUES (
        %s, %s, %s,
        %s,
        'ticker', %s,
        %s, %s, %s
    )
    ON CONFLICT DO NOTHING
"""


def _make_event_id(event_key: str, ticker: str) -> str:
    return hashlib.sha256(f"{event_key}:{ticker}".encode()).hexdigest()[:32]


def _ensure_partitions(conn, start: datetime.datetime, end: datetime.datetime) -> None:
    """Create monthly partitions for behavioral_events that don't already exist."""
    current = start.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    end_month = end.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    with conn.cursor() as cur:
        while current <= end_month:
            next_month = (current + datetime.timedelta(days=32)).replace(day=1)
            name = f"behavioral_events_{current.strftime('%Y_%m')}"
            from_val = current.date().isoformat()
            to_val = next_month.date().isoformat()

            cur.execute(
                f"SELECT 1 FROM pg_tables WHERE schemaname = 'public' AND tablename = '{name}'"
            )
            if not cur.fetchone():
                cur.execute(
                    f"CREATE TABLE IF NOT EXISTS {name}"
                    f" PARTITION OF behavioral_events"
                    f" FOR VALUES FROM ('{from_val}') TO ('{to_val}')"
                )
                logger.info("Created partition %s", name)
            current = next_month
    conn.commit()


def _resolve_tenant_id(conn, tenant_name: str) -> str:
    with conn.cursor() as cur:
        cur.execute("SELECT tenant_id FROM tenant WHERE tenant_name = %s", (tenant_name,))
        row = cur.fetchone()
        if not row:
            raise ValueError(f"Tenant '{tenant_name}' not found in Postgres.")
        return row["tenant_id"] if isinstance(row, dict) else row[0]


def _fetch_valid_profile_ids(conn, profile_ids: list) -> set:
    with conn.cursor() as cur:
        cur.execute(
            "SELECT profile_id FROM cdp_profiles WHERE profile_id = ANY(%s)",
            (profile_ids,),
        )
        return {
            row["profile_id"] if isinstance(row, dict) else row[0]
            for row in cur.fetchall()
        }


def _fetch_arango_events(settings: DatabaseSettings, start_iso: str, end_iso: str) -> list:
    db = settings.get_arango_db()
    if not db:
        return []
    try:
        cursor = db.aql.execute(
            _ARANGO_QUERY,
            bind_vars={"start_time": start_iso, "end_time": end_iso},
        )
        results = list(cursor)
        logger.info("Fetched %d event-ticker rows from ArangoDB (%s → %s)", len(results), start_iso, end_iso)
        return results
    except Exception as e:
        logger.error("ArangoDB query failed: %s", e)
        return []


def run_backfill(settings: DatabaseSettings, start_iso: str, end_iso: str) -> None:
    conn = settings.get_pg_connection()
    try:
        tenant_id = _resolve_tenant_id(conn, TARGET_TENANT)

        start_dt = datetime.datetime.fromisoformat(start_iso)
        end_dt = datetime.datetime.fromisoformat(end_iso)
        _ensure_partitions(conn, start_dt, end_dt)

        rows = _fetch_arango_events(settings, start_iso, end_iso)
        if not rows:
            log_event(logger, "behavioral_events_backfill_complete", inserted=0, reason="no_events")
            return

        # Drop orphaned profiles (not in cdp_profiles)
        arango_pids = list({r["profile_id"] for r in rows})
        valid_pids = _fetch_valid_profile_ids(conn, arango_pids)
        skipped = len(arango_pids) - len(valid_pids)
        if skipped:
            logger.info("Skipping %d orphaned profile(s) not in cdp_profiles", skipped)
        rows = [r for r in rows if r["profile_id"] in valid_pids]

        if not rows:
            log_event(logger, "behavioral_events_backfill_complete", inserted=0, reason="all_orphaned")
            return

        inserted = 0
        with conn.cursor() as cur:
            for row in rows:
                event_id = _make_event_id(row["event_key"], row["ticker"])
                created_at = datetime.datetime.fromisoformat(
                    row["created_at"].replace("Z", "+00:00")
                )
                cur.execute(_INSERT_SQL, (
                    event_id,
                    tenant_id,
                    row["profile_id"],
                    row["event_metric_name"],
                    row["ticker"],
                    int(row["points"] or 0),
                    json.dumps(row["event_data"] or {}),
                    created_at,
                ))
                inserted += 1
        conn.commit()

        log_event(logger, "behavioral_events_backfill_complete",
                  fetched=len(rows), inserted=inserted, skipped_orphaned=skipped)

    except Exception as e:
        conn.rollback()
        logger.error("Backfill failed: %s", e)
        raise
    finally:
        conn.close()


if __name__ == "__main__":
    import sys

    # Default: 90-day backfill (run once).
    # Pass --hours N for incremental mode (e.g. hourly cron: --hours 2).
    hours = None
    if "--hours" in sys.argv:
        idx = sys.argv.index("--hours")
        hours = int(sys.argv[idx + 1])

    settings = DatabaseSettings()
    now = datetime.datetime.now(datetime.timezone.utc)
    end = now.replace(minute=0, second=0, microsecond=0)
    start = end - (datetime.timedelta(hours=hours) if hours else datetime.timedelta(days=90))

    logger.info(
        "Starting behavioral_events sync | Tenant: %s | Window: %s → %s",
        TARGET_TENANT, start.isoformat(), end.isoformat(),
    )
    run_backfill(settings, start.isoformat(), end.isoformat())
