"""
Pre-compute abandoned-cart tickers per profile.

Logic (last 7 days of events per profile):
  Reason A: ticker viewed >= 3 times
  Reason B: order-preview event with no matching order-created for same ticker

For each abandoned (profile, ticker):
  1. Resolve viewed_at = earliest relevant event timestamp
  2. Look up viewed_price from market_snapshot_history (closest row <= viewed_at)
  3. Join with market_snapshot (current price)
  4. Keep only tickers where drop_pct = 1 - (current / viewed) >= 0.10

Writes the final list to cdp_profiles.ext_data.abandoned_tickers:
  [
    {"ticker": "FPT", "reason": "viewed_3x", "viewed_at": "...",
     "viewed_price": 120.5, "current_price": 105.2, "drop_pct": 12.7},
    ...
  ]

Run BEFORE the campaign engine (hourly cron).
"""

import json
import logging
import os
from collections import defaultdict
from datetime import datetime, timedelta, timezone

from dotenv import load_dotenv

load_dotenv()

from data_utils.settings import DatabaseSettings

logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)s | %(message)s")
logger = logging.getLogger(__name__)

TARGET_TENANT = os.getenv("TARGET_TENANT", "master")
LOOKBACK_DAYS = int(os.getenv("ABANDONED_LOOKBACK_DAYS", "7"))
MIN_VIEW_COUNT = int(os.getenv("ABANDONED_MIN_VIEW_COUNT", "3"))
PRICE_DROP_THRESHOLD = float(os.getenv("ABANDONED_DROP_THRESHOLD", "0.10"))  # 10%


def _fetch_ticker_events(arango_db) -> list[dict]:
    """Pull ticker-view / order-preview / order-created events from last 7 days."""
    cutoff = (datetime.now(timezone.utc) - timedelta(days=LOOKBACK_DAYS)).isoformat()
    aql = """
    FOR e IN cdp_trackingevent
        FILTER e.metricName IN ["ticker-view", "order-preview", "order-created"]
        FILTER e.createdAt >= @cutoff
        FILTER e.refProfileId != null
        LET single = e.eventData.instrument_id
        LET list   = e.eventData.instrument_id_list
        LET tickers = (
            single != null AND single != ""
            ? [single]
            : (IS_ARRAY(list) AND LENGTH(list) > 0 ? list : [])
        )
        FOR t IN tickers
            FILTER t != null AND t != ""
            RETURN {
                profile_key: e.refProfileId,
                ticker: t,
                metric: e.metricName,
                ts: e.createdAt
            }
    """
    cursor = arango_db.aql.execute(aql, bind_vars={"cutoff": cutoff}, batch_size=5000)
    return list(cursor)


def _detect_abandoned(events: list[dict]) -> dict[str, dict[str, dict]]:
    """
    Returns: {profile_key: {ticker: {"reason": ..., "viewed_at": iso}}}
    """
    # Group events per (profile, ticker)
    grouped: dict[tuple[str, str], dict[str, list[str]]] = defaultdict(
        lambda: {"views": [], "previews": [], "creates": []}
    )
    for ev in events:
        key = (ev["profile_key"], ev["ticker"])
        metric = ev["metric"]
        ts = ev["ts"]
        if metric == "ticker-view":
            grouped[key]["views"].append(ts)
        elif metric == "order-preview":
            grouped[key]["previews"].append(ts)
        elif metric == "order-created":
            grouped[key]["creates"].append(ts)

    abandoned: dict[str, dict[str, dict]] = defaultdict(dict)
    for (pid, ticker), buckets in grouped.items():
        reason = None
        earliest = None

        # Reason A: viewed >= 3 times
        if len(buckets["views"]) >= MIN_VIEW_COUNT:
            reason = f"viewed_{len(buckets['views'])}x"
            earliest = min(buckets["views"])

        # Reason B: previewed but never created (any create cancels the flag)
        if buckets["previews"] and not buckets["creates"]:
            preview_earliest = min(buckets["previews"])
            if reason is None:
                reason = "preview_no_execute"
                earliest = preview_earliest
            else:
                earliest = min(earliest, preview_earliest)
                reason = "viewed_and_preview_no_execute"

        if reason:
            abandoned[pid][ticker] = {"reason": reason, "viewed_at": earliest}

    return abandoned


def _lookup_historical_prices(conn, abandoned: dict) -> dict[tuple[str, str], float]:
    """
    For each (profile, ticker), find the price in market_snapshot_history
    closest to viewed_at (but at-or-before).
    Returns: {(profile_key, ticker): viewed_price}
    """
    result: dict[tuple[str, str], float] = {}
    with conn.cursor() as cur:
        for pid, tickers in abandoned.items():
            for ticker, info in tickers.items():
                cur.execute(
                    """
                    SELECT price
                    FROM market_snapshot_history
                    WHERE symbol = %s AND snapshot_at <= %s
                    ORDER BY snapshot_at DESC
                    LIMIT 1
                    """,
                    (ticker, info["viewed_at"]),
                )
                row = cur.fetchone()
                if row and row["price"] is not None:
                    result[(pid, ticker)] = float(row["price"])
    return result


def _load_current_prices(conn, symbols: set[str]) -> dict[str, float]:
    """Fetch current price from market_snapshot for the given symbols."""
    if not symbols:
        return {}
    with conn.cursor() as cur:
        cur.execute(
            "SELECT symbol, price FROM market_snapshot WHERE symbol = ANY(%s)",
            (list(symbols),),
        )
        return {r["symbol"]: float(r["price"]) for r in cur.fetchall() if r["price"] is not None}


def _write_abandoned_to_pg(conn, tenant_id: str, alerts: dict[str, list[dict]]) -> tuple[int, int]:
    """
    Write the list of actionable abandoned tickers to ext_data per profile.
    Clears the field for profiles that have nothing actionable.
    Returns (with_alerts, cleared).
    """
    with_alerts = 0
    cleared = 0

    with conn.cursor() as cur:
        # Write alerts
        for profile_id, items in alerts.items():
            if items:
                cur.execute(
                    """
                    UPDATE cdp_profiles
                    SET ext_data = jsonb_set(
                        COALESCE(ext_data, '{}'::jsonb),
                        '{abandoned_tickers}',
                        %s::jsonb
                    ),
                    updated_at = now()
                    WHERE tenant_id = %s AND profile_id = %s
                    """,
                    (json.dumps(items), tenant_id, profile_id),
                )
                with_alerts += cur.rowcount

        # Clear stale lists for profiles that had abandoned_tickers but don't anymore
        cur.execute(
            """
            UPDATE cdp_profiles
            SET ext_data = ext_data - 'abandoned_tickers',
                updated_at = now()
            WHERE tenant_id = %s
              AND ext_data ? 'abandoned_tickers'
              AND NOT (profile_id = ANY(%s))
            """,
            (tenant_id, list(alerts.keys())),
        )
        cleared = cur.rowcount

    conn.commit()
    return with_alerts, cleared


def run(tenant_name: str | None = None):
    settings = DatabaseSettings()
    conn = settings.get_pg_connection()
    arango_db = settings.get_arango_db()

    tenant = tenant_name or TARGET_TENANT
    with conn.cursor() as cur:
        cur.execute("SELECT tenant_id FROM tenant WHERE tenant_name = %s", (tenant,))
        row = cur.fetchone()
        if not row:
            logger.error("Tenant '%s' not found", tenant)
            conn.close()
            return
        tenant_id = str(row["tenant_id"])

    logger.info("Fetching ticker events (last %d days)...", LOOKBACK_DAYS)
    events = _fetch_ticker_events(arango_db)
    logger.info("Fetched %d events", len(events))

    logger.info("Detecting abandoned tickers...")
    abandoned = _detect_abandoned(events)
    total_pairs = sum(len(v) for v in abandoned.values())
    logger.info("Found %d (profile, ticker) abandoned pairs across %d profiles",
                total_pairs, len(abandoned))

    logger.info("Looking up historical prices at view-time...")
    viewed_prices = _lookup_historical_prices(conn, abandoned)
    logger.info("Resolved historical price for %d pairs", len(viewed_prices))

    all_symbols = {t for tickers in abandoned.values() for t in tickers}
    current_prices = _load_current_prices(conn, all_symbols)
    logger.info("Loaded current prices for %d symbols", len(current_prices))

    # Build final actionable alert list per profile
    alerts: dict[str, list[dict]] = defaultdict(list)
    for pid, tickers in abandoned.items():
        for ticker, info in tickers.items():
            viewed_price = viewed_prices.get((pid, ticker))
            current_price = current_prices.get(ticker)
            if not viewed_price or not current_price or viewed_price <= 0:
                continue
            drop_pct = 1.0 - (current_price / viewed_price)
            if drop_pct < PRICE_DROP_THRESHOLD:
                continue
            alerts[pid].append({
                "ticker": ticker,
                "reason": info["reason"],
                "viewed_at": info["viewed_at"],
                "viewed_price": round(viewed_price, 2),
                "current_price": round(current_price, 2),
                "drop_pct": round(drop_pct * 100, 2),
            })

    actionable_pairs = sum(len(v) for v in alerts.values())
    logger.info("Actionable (drop >= %.0f%%): %d pairs across %d profiles",
                PRICE_DROP_THRESHOLD * 100, actionable_pairs, len(alerts))

    with_alerts, cleared = _write_abandoned_to_pg(conn, tenant_id, dict(alerts))
    logger.info("Wrote alerts for %d profiles | cleared stale lists on %d profiles",
                with_alerts, cleared)

    conn.close()


if __name__ == "__main__":
    run()
