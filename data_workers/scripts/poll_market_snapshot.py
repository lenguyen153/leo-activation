"""
Market Snapshot Poller
======================
Every 15 minutes:
  1. Discover tickers that appear in any profile's ticker-view / order-preview
     events over the last 7 days (ArangoDB).
  2. Fetch current market info for each ticker from the internal market API.
  3. Upsert into `market_snapshot` (current state).
  4. Insert into `market_snapshot_history` (append-only, used to look up
     price at the time a user viewed a ticker).

Run:
  python -m data_workers.scripts.poll_market_snapshot
"""

import os
import time
from datetime import datetime, timedelta, timezone

import httpx
from dotenv import load_dotenv

load_dotenv()

from data_utils.logging_config import configure_logging, get_logger, log_event
from data_utils.settings import DatabaseSettings

configure_logging()
logger = get_logger(__name__)

MARKET_API_URL = os.getenv(
    "MARKET_API_URL",
    "http://172.60.1.2:8889/api/market/info",
)
HTTP_TIMEOUT = int(os.getenv("MARKET_API_TIMEOUT", "10"))
# Batch throttle: pause HTTP_BATCH_PAUSE_MS after every HTTP_BATCH_SIZE calls.
# Default: sleep 1s every 50 calls. Set HTTP_BATCH_PAUSE_MS=0 to disable.
HTTP_BATCH_SIZE = int(os.getenv("MARKET_API_BATCH_SIZE", "50"))
HTTP_BATCH_PAUSE_MS = int(os.getenv("MARKET_API_BATCH_PAUSE_MS", "1000"))


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


def _fetch_market_info(client: httpx.Client, ticker: str) -> tuple[dict | None, object]:
    """
    Call the internal market API. Returns (row, raw_payload).
    row is the first result dict or None; raw_payload is the raw response
    (useful for debugging why we got no row).
    """
    try:
        resp = client.get(
            MARKET_API_URL,
            params={
                "mode": "now",
                "target_type": "symbol",
                "ticket": ticker,
                "limit": 1,
            },
        )
        resp.raise_for_status()
        data = resp.json()
    except Exception as e:
        logger.warning("API call failed for %s: %s", ticker, e)
        return None, None

    # The API may wrap results in a list or a "data" key — tolerate both.
    if isinstance(data, dict) and "data" in data:
        rows = data["data"]
    elif isinstance(data, list):
        rows = data
    else:
        rows = [data]

    if not rows:
        return None, data
    first = rows[0] if isinstance(rows[0], dict) else None
    return first, data


def _extract_fields(row: dict) -> dict:
    """
    Map the market API response to our schema.

    Real API shape: {"content": {"CurrentPrice": ..., "ReferencePrice": ..., ...}}
    - CurrentPrice = 0 when the stock hasn't traded today yet
    - ReferencePrice = previous session close (always set for listed tickers)
    - AccumulatedVolume = cumulative daily volume
    - PercentChange = already computed by the API
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

    logger.info("Loading full ticker universe from instruments table...")
    tickers = _load_all_tickers(conn)
    logger.info("Found %d tickers to poll", len(tickers))

    polled = 0
    skipped_no_row = 0
    skipped_no_price = 0
    logged_ok_sample = False
    logged_no_price_sample = False
    logged_empty_sample = False

    batch_pause_s = HTTP_BATCH_PAUSE_MS / 1000.0

    # Re-use one HTTP client for the whole poll so connections are pooled and
    # we don't exhaust local/ephemeral TCP ports.
    with httpx.Client(timeout=HTTP_TIMEOUT) as client:
        for idx, symbol in enumerate(tickers):
            row, raw = _fetch_market_info(client, symbol)
            # Batch throttle: sleep every HTTP_BATCH_SIZE calls (not on the last one).
            if (
                batch_pause_s > 0
                and HTTP_BATCH_SIZE > 0
                and (idx + 1) % HTTP_BATCH_SIZE == 0
                and (idx + 1) < len(tickers)
            ):
                time.sleep(batch_pause_s)
            if not row:
                skipped_no_row += 1
                if not logged_empty_sample:
                    logger.info("Sample empty-row payload for %s: %s", symbol, raw)
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
    conn.commit()
    conn.close()
    log_event(logger, "volume_analytics_updated", symbols=updated_vol)


if __name__ == "__main__":
    run()
