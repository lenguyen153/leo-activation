"""
Pre-compute activity drop metric for the Sudden Inactivity campaign rule.

Logic:
  1. For each active profile, count engagement events per week over the last 12 weeks
     (source: ArangoDB cdp_trackingevent collection).
     Engagement = ticker-view, portfolio-view, order-*, search, news-view, login, etc.
  2. Compute baseline = average weekly engagement over weeks 3-12 (excluding last 2 weeks).
  3. Compute recent  = average weekly engagement over the last 2 weeks.
  4. activity_drop_pct = 1 - (recent / baseline).  If baseline is 0, skip.
  5. Write result to cdp_profiles.ext_data.activity_drop_pct in PostgreSQL.

Run:
  python -m data_workers.scripts.compute_activity_drop

Schedule: run this BEFORE the campaign engine (e.g., at minute :50 of each hour).
"""

import os
from datetime import datetime, timedelta, timezone

from dotenv import load_dotenv

load_dotenv()

from data_utils.logging_config import configure_logging, get_logger, log_event
from data_utils.settings import DatabaseSettings

configure_logging()
logger = get_logger(__name__)

TARGET_TENANT = os.getenv("TARGET_TENANT", "master")
TARGET_SEGMENT = os.getenv("TARGET_SEGMENT", "Active in last 3 months")

# How many weeks of history to consider
BASELINE_WEEKS = 12
# Recent window (last N weeks) to compare against baseline
RECENT_WEEKS = 2
# Engagement events that prove the user is actively using the app.
# Excludes passive/automatic events (tab-blur, tab-focus, idle-*, accept-tracking)
# and low-signal events (page-view is too noisy, component-hover too passive).
ENGAGEMENT_METRICS = [
    "ticker-view",
    "portfolio-view",
    "watchlist-page-view",
    "overview-view",
    "trading-view",
    "order-preview",
    "order-created",
    "ticker-financial-view",
    "search",
    "news-view",
    "login-success",
]


def _fetch_engagement_events_from_arango(arango_db, segment_name: str) -> list[dict]:
    """
    Query ArangoDB for engagement events per profile over the last BASELINE_WEEKS weeks.
    Returns list of {profile_key, event_ts} dicts.
    """
    cutoff = datetime.now(timezone.utc) - timedelta(weeks=BASELINE_WEEKS)
    cutoff_iso = cutoff.isoformat()

    aql = """
    FOR p IN cdp_profile
        FILTER @seg IN p.inSegments[*].name
        FOR e IN cdp_trackingevent
            FILTER e.refProfileId == p._key
            FILTER e.metricName IN @metrics
            FILTER e.createdAt >= @cutoff
            RETURN {
                profile_key: p._key,
                event_ts: e.createdAt
            }
    """
    cursor = arango_db.aql.execute(
        aql,
        bind_vars={"seg": segment_name, "metrics": ENGAGEMENT_METRICS, "cutoff": cutoff_iso},
        batch_size=5000,
    )
    return list(cursor)


def _compute_drops(events: list[dict]) -> dict[str, float]:
    """
    Group events by profile, bucket into weeks, compute drop percentage.
    Returns {profile_key: drop_pct} for profiles with meaningful baseline.
    """
    from collections import defaultdict

    now = datetime.now(timezone.utc)

    # Group events by profile → list of week numbers (0 = this week, 1 = last week, ...)
    profile_weeks: dict[str, list[int]] = defaultdict(list)

    for ev in events:
        ts_str = ev["event_ts"]
        if isinstance(ts_str, str):
            # Parse ISO timestamp — handle with/without timezone
            ts_str = ts_str.replace("Z", "+00:00")
            try:
                ts = datetime.fromisoformat(ts_str)
            except ValueError:
                continue
        else:
            ts = ts_str

        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=timezone.utc)

        weeks_ago = int((now - ts).days / 7)
        if 0 <= weeks_ago < BASELINE_WEEKS:
            profile_weeks[ev["profile_key"]].append(weeks_ago)

    # Compute drop per profile
    drops: dict[str, float] = {}

    for profile_key, week_list in profile_weeks.items():
        # Count events per week
        week_counts: dict[int, int] = defaultdict(int)
        for w in week_list:
            week_counts[w] += 1

        # Baseline: weeks RECENT_WEEKS .. BASELINE_WEEKS-1 (older weeks)
        baseline_weeks_range = range(RECENT_WEEKS, BASELINE_WEEKS)
        baseline_counts = [week_counts.get(w, 0) for w in baseline_weeks_range]
        baseline_avg = sum(baseline_counts) / len(baseline_counts) if baseline_counts else 0

        if baseline_avg < 1.0:
            # User had negligible activity — not a meaningful baseline
            continue

        # Recent: weeks 0 .. RECENT_WEEKS-1
        recent_counts = [week_counts.get(w, 0) for w in range(RECENT_WEEKS)]
        recent_avg = sum(recent_counts) / len(recent_counts) if recent_counts else 0

        drop_pct = 1.0 - (recent_avg / baseline_avg)
        drops[profile_key] = round(drop_pct, 4)

    return drops


def _write_drops_to_pg(pg_conn, tenant_id: str, drops: dict[str, float]) -> int:
    """
    Write activity_drop_pct into cdp_profiles.ext_data for each profile.
    Uses jsonb_set to merge without overwriting other ext_data keys.
    """
    updated = 0
    with pg_conn.cursor() as cur:
        for profile_id, drop_pct in drops.items():
            cur.execute(
                """
                UPDATE cdp_profiles
                SET ext_data = jsonb_set(
                    COALESCE(ext_data, '{}'::jsonb),
                    '{activity_drop_pct}',
                    %s::jsonb
                ),
                updated_at = now()
                WHERE tenant_id = %s AND profile_id = %s
                """,
                (str(drop_pct), tenant_id, profile_id),
            )
            updated += cur.rowcount
    pg_conn.commit()
    return updated


def run(tenant_name: str | None = None):
    settings = DatabaseSettings()
    pg_conn = settings.get_pg_connection()
    arango_db = settings.get_arango_db()

    tenant = tenant_name or TARGET_TENANT

    # Resolve tenant UUID
    with pg_conn.cursor() as cur:
        cur.execute("SELECT tenant_id FROM tenant WHERE tenant_name = %s", (tenant,))
        row = cur.fetchone()
        if not row:
            logger.error("Tenant '%s' not found", tenant)
            pg_conn.close()
            return
        tenant_id = str(row["tenant_id"])

    logger.info("Fetching engagement events from ArangoDB (last %d weeks)...", BASELINE_WEEKS)
    events = _fetch_engagement_events_from_arango(arango_db, TARGET_SEGMENT)
    logger.info("Fetched %d events", len(events))

    logger.info("Computing activity drops...")
    drops = _compute_drops(events)
    logger.info("Found %d profiles with meaningful baseline", len(drops))

    # Log distribution
    severe = sum(1 for d in drops.values() if d >= 0.7)
    moderate = sum(1 for d in drops.values() if 0.3 <= d < 0.7)
    logger.info("Distribution: %d severe (>=70%%), %d moderate (30-70%%)", severe, moderate)

    logger.info("Writing to PostgreSQL ext_data.activity_drop_pct...")
    updated = _write_drops_to_pg(pg_conn, tenant_id, drops)
    log_event(logger, "activity_drop_computed", updated=updated, severe=severe, moderate=moderate)

    pg_conn.close()


if __name__ == "__main__":
    run()
