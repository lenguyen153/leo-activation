"""
Market Snapshot Poller
======================
Every 15 minutes:
  1. Load every ticker from the `instruments` table (full VN exchange universe).
  2. Fetch current market data from the internal Redis cache (key: latest:{SYMBOL}).
  3. Upsert into `market_snapshot` (current state).
  4. Insert into `market_snapshot_history` (append-only, used to look up
     price at the time a user viewed a ticker).

Run:
  python -m data_workers.scripts.poll_market_snapshot
"""

import json
import os
import time

import redis as redis_lib
from dotenv import load_dotenv

load_dotenv()

from data_utils.logging_config import configure_logging, get_logger, log_event
from data_utils.settings import DatabaseSettings

configure_logging()
logger = get_logger(__name__)

# Market data Redis — separate from the campaign-engine/frequency-cap Redis (REDIS_URL).
MARKET_REDIS_HOST = os.getenv("MARKET_REDIS_HOST", "172.60.1.4")
MARKET_REDIS_PORT = int(os.getenv("MARKET_REDIS_PORT", "6379"))
MARKET_REDIS_DB = int(os.getenv("MARKET_REDIS_DB", "0"))
MARKET_REDIS_PASSWORD = os.getenv("MARKET_REDIS_PASSWORD", "")

# Batch throttle: pause MARKET_BATCH_PAUSE_MS after every MARKET_BATCH_SIZE reads.
# Redis is fast — default 0 (no pause). Raise if the market Redis shows load issues.
MARKET_BATCH_SIZE = int(os.getenv("MARKET_API_BATCH_SIZE", "50"))
MARKET_BATCH_PAUSE_MS = int(os.getenv("MARKET_API_BATCH_PAUSE_MS", "0"))


def _load_all_tickers(conn) -> list[str]:
    """
    Load every stock ticker from the `instruments` table — the full VN
    exchange universe (~1500 symbols), not just what users have viewed.
    This is what enables:
      - price history for ANY ticker a user might view (even first-time)
      - meaningful avg_30d_volume / is_volume_spike after 30 days
    """
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT DISTINCT symbol
            FROM instruments
            WHERE symbol IS NOT NULL AND symbol <> ''
            ORDER BY symbol
            """
        )
        return [r["symbol"] for r in cur.fetchall() if r["symbol"]]


def _fetch_market_info(redis_client: redis_lib.Redis, ticker: str) -> tuple[dict | None, object]:
    """
    Read the latest market snapshot for a ticker from Redis (key: latest:{ticker}).
    Returns (row_dict, raw_str). row is None when the key is absent or unparseable.
    """
    raw = redis_client.get(f"latest:{ticker}")
    if not raw:
        return None, None
    try:
        data = json.loads(raw)
        if not isinstance(data, dict):
            return None, raw
        return data, raw
    except (json.JSONDecodeError, TypeError) as e:
        logger.warning("Redis parse failed for %s: %s", ticker, e)
        return None, raw


def _extract_fields(row: dict) -> dict:
    """
    Map the Redis market snapshot to our schema.

    Redis key latest:{SYMBOL} shape: {"CurrentPrice": ..., "ReferencePrice": ..., ...}
    - CurrentPrice = 0 when the stock hasn't traded today yet
    - ReferencePrice = previous session close (always set for listed tickers)
    - AccumulatedVolume = cumulative daily volume
    - PercentChange = already computed by the data source
    """
    content = row.get("content") if isinstance(row.get("content"), dict) else row

    def _nz(v):
        """Normalize: None or zero → None; else numeric."""
        try:
            if v is None:
                return None
            f = float(v)
            return f if f > 0 else None
        except (ValueError, TypeError):
            return None

    current   = _nz(content.get("CurrentPrice"))
    reference = _nz(content.get("ReferencePrice"))
    open_px   = _nz(content.get("OpenPrice"))
    vwap      = _nz(content.get("VWAP"))

    # Prefer live trade price; fall back to VWAP / open / yesterday's close
    # so illiquid tickers still get tracked (and their 'viewed_price' lookup works).
    price = current or vwap or open_px or reference

    # PercentChange is provided by the API — use it when CurrentPrice is live.
    change_pct = None
    api_pct = content.get("PercentChange")
    if current is not None and api_pct is not None:
        try:
            change_pct = round(float(api_pct), 3)
        except (ValueError, TypeError):
            change_pct = None

    volume = content.get("AccumulatedVolume")
    try:
        volume = int(volume) if volume is not None else None
    except (ValueError, TypeError):
        volume = None

    return {
        "price": price,
        "change_percent_24h": change_pct,
        "current_volume": volume,
        "avg_30d_volume": None,           # computed post-poll from history
        "is_volume_spike": None,          # computed post-poll from history
        "platform_trending_score": None,  # not exposed by this API
    }


def _upsert_snapshot(conn, symbol: str, fields: dict) -> None:
    """Upsert current state and append to history."""
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO market_snapshot
              (symbol, price, change_percent_24h, current_volume, avg_30d_volume,
               is_volume_spike, platform_trending_score, last_updated)
            VALUES (%s, %s, %s, %s, %s, %s, %s, now())
            ON CONFLICT (symbol) DO UPDATE SET
              price                   = EXCLUDED.price,
              change_percent_24h      = EXCLUDED.change_percent_24h,
              current_volume          = EXCLUDED.current_volume,
              avg_30d_volume          = EXCLUDED.avg_30d_volume,
              is_volume_spike         = EXCLUDED.is_volume_spike,
              platform_trending_score = EXCLUDED.platform_trending_score,
              last_updated            = now()
            """,
            (
                symbol,
                fields["price"],
                fields["change_percent_24h"],
                fields["current_volume"],
                fields["avg_30d_volume"],
                fields["is_volume_spike"],
                fields["platform_trending_score"],
            ),
        )

        cur.execute(
            """
            INSERT INTO market_snapshot_history
              (symbol, price, change_percent_24h, current_volume, snapshot_at)
            VALUES (%s, %s, %s, %s, now())
            ON CONFLICT (symbol, snapshot_at) DO NOTHING
            """,
            (symbol, fields["price"], fields["change_percent_24h"], fields["current_volume"]),
        )


def _compute_volume_analytics(conn) -> int:
    """
    For every symbol in market_snapshot, compute:
      - avg_30d_volume = average daily volume (last 30 days, 1 row per day = max)
      - is_volume_spike = current_volume > (avg_30d_volume * 2)

    Uses the history table: total_volume is cumulative-per-day, so MAX per day
    gives the daily close volume. Skips days with NULL or 0.
    """
    with conn.cursor() as cur:
        cur.execute(
            """
            WITH daily AS (
                SELECT
                    symbol,
                    DATE(snapshot_at) AS d,
                    MAX(current_volume) AS daily_vol
                FROM market_snapshot_history
                WHERE snapshot_at >= NOW() - INTERVAL '30 days'
                  AND current_volume IS NOT NULL
                GROUP BY symbol, DATE(snapshot_at)
            ),
            agg AS (
                SELECT symbol, AVG(daily_vol)::BIGINT AS avg_vol
                FROM daily
                WHERE daily_vol > 0
                GROUP BY symbol
                HAVING COUNT(*) >= 1
            )
            UPDATE market_snapshot m
            SET avg_30d_volume = agg.avg_vol,
                is_volume_spike = (m.current_volume IS NOT NULL
                                   AND agg.avg_vol > 0
                                   AND m.current_volume > agg.avg_vol * 2)
            FROM agg
            WHERE m.symbol = agg.symbol
            """
        )
        return cur.rowcount


def run():
    settings = DatabaseSettings()
    conn = settings.get_pg_connection()

    try:
        market_redis = redis_lib.Redis(
            host=MARKET_REDIS_HOST,
            port=MARKET_REDIS_PORT,
            db=MARKET_REDIS_DB,
            password=MARKET_REDIS_PASSWORD or None,
            socket_connect_timeout=5,
            decode_responses=True,
        )
        market_redis.ping()
        logger.info("Connected to market Redis at %s:%s/db%s", MARKET_REDIS_HOST, MARKET_REDIS_PORT, MARKET_REDIS_DB)
    except Exception as e:
        logger.error("Cannot connect to market Redis: %s", e)
        conn.close()
        return

    logger.info("Loading full ticker universe from instruments table...")
    tickers = _load_all_tickers(conn)
    logger.info("Found %d tickers to poll", len(tickers))

    polled = 0
    skipped_no_row = 0
    skipped_no_price = 0
    logged_ok_sample = False
    logged_no_price_sample = False
    logged_empty_sample = False

    batch_pause_s = MARKET_BATCH_PAUSE_MS / 100.0

    for idx, symbol in enumerate(tickers):
        row, raw = _fetch_market_info(market_redis, symbol)
        # Batch throttle (configurable via env; default 0 = no pause for Redis).
        if (
            batch_pause_s > 0
            and MARKET_BATCH_SIZE > 0
            and (idx + 1) % MARKET_BATCH_SIZE == 0
            and (idx + 1) < len(tickers)
        ):
            time.sleep(batch_pause_s)
        if not row:
            skipped_no_row += 1
            if not logged_empty_sample:
                logger.info("Sample missing-key for %s: raw=%s", symbol, raw)
                logged_empty_sample = True
            continue
        if not logged_ok_sample:
            logger.info("Sample OK row for %s: %s", symbol, row)
            logged_ok_sample = True
        fields = _extract_fields(row)
        if fields["price"] is None:
            if not logged_no_price_sample:
                logger.info("Sample no-price row for %s: %s", symbol, row)
                logged_no_price_sample = True
            skipped_no_price += 1
            continue
        try:
            _upsert_snapshot(conn, symbol, fields)
            polled += 1
        except Exception as e:
            logger.error("DB upsert failed for %s: %s", symbol, e)
            conn.rollback()
            continue

    conn.commit()

    log_event(logger, "market_snapshot_polled",
              polled=polled, skipped_no_api_row=skipped_no_row, skipped_no_price=skipped_no_price)

    # Compute volume analytics from accumulated history
    updated_vol = _compute_volume_analytics(conn)

    # Purge rows older than 35 days (30d needed for avg_30d_volume + 5d buffer).
    with conn.cursor() as cur:
        cur.execute(
            "DELETE FROM market_snapshot_history WHERE snapshot_at < NOW() - INTERVAL '35 days'"
        )
        purged = cur.rowcount

    conn.commit()
    conn.close()
    log_event(logger, "volume_analytics_updated", symbols=updated_vol)
    if purged:
        log_event(logger, "market_history_purged", rows=purged)


if __name__ == "__main__":
    run()
