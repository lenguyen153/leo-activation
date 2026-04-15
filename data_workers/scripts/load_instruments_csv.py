"""
Bulk-load the Vietnam stock ticker universe into the `instruments` table
from a CSV file. Idempotent (ON CONFLICT DO NOTHING) so re-runs are safe.

CSV format (flexible — column names are auto-detected, case-insensitive):
  Required: symbol
  Optional: name, type, sector, exchange
  Default type = 'STOCK' if missing.

Run:
  python -m data_workers.scripts.load_instruments_csv path/to/tickers.csv

  # Or via env var:
  INSTRUMENTS_CSV=/path/to/tickers.csv python -m data_workers.scripts.load_instruments_csv
"""

import csv
import json
import logging
import os
import sys

from dotenv import load_dotenv

load_dotenv()

from data_utils.settings import DatabaseSettings

logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)s | %(message)s")
logger = logging.getLogger(__name__)


def _normalize_headers(fieldnames: list[str]) -> dict[str, str]:
    """Map lower-cased header → actual CSV header, tolerant of case/whitespace."""
    return {h.strip().lower(): h for h in fieldnames if h}


def _parse_csv(path: str) -> list[dict]:
    rows: list[dict] = []
    with open(path, newline="", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        if not reader.fieldnames:
            raise ValueError(f"CSV {path} has no header row")

        hmap = _normalize_headers(reader.fieldnames)
        sym_col = hmap.get("symbol") or hmap.get("ticker") or hmap.get("code")
        if not sym_col:
            raise ValueError("CSV must have a 'symbol' column (or 'ticker' / 'code')")

        name_col     = hmap.get("name") or hmap.get("company") or hmap.get("company_name")
        type_col     = hmap.get("type") or hmap.get("asset_type")
        sector_col   = hmap.get("sector") or hmap.get("industry")
        exchange_col = hmap.get("exchange") or hmap.get("market")

        for row in reader:
            sym = (row.get(sym_col) or "").strip().upper()
            if not sym:
                continue
            rows.append({
                "symbol": sym,
                "name": (row.get(name_col) or sym).strip() if name_col else sym,
                "type": (row.get(type_col) or "STOCK").strip().upper() if type_col else "STOCK",
                "sector": (row.get(sector_col) or "").strip() or None if sector_col else None,
                "exchange": (row.get(exchange_col) or "").strip() or None if exchange_col else None,
            })
    return rows


INSERT_SQL = """
INSERT INTO instruments
    (tenant_id, symbol, name, type, sector, meta_data)
VALUES (NULL, %s, %s, %s, %s, %s::jsonb)
ON CONFLICT (tenant_id, symbol) DO NOTHING
"""


def _bulk_upsert(conn, instruments: list[dict]) -> tuple[int, int]:
    """
    Bulk insert using DBAPI executemany. Returns (inserted, skipped_existing).
    Idempotent — ON CONFLICT (tenant_id, symbol) DO NOTHING.
    """
    if not instruments:
        return 0, 0

    values = [
        (
            inst["symbol"],
            inst["name"],
            inst["type"],
            inst["sector"],
            json.dumps({"exchange": inst["exchange"]}) if inst["exchange"] else "{}",
        )
        for inst in instruments
    ]

    with conn.cursor() as cur:
        cur.execute("SELECT COUNT(*) AS n FROM instruments")
        before_count = cur.fetchone()["n"]

        cur.executemany(INSERT_SQL, values)

        cur.execute("SELECT COUNT(*) AS n FROM instruments")
        after_count = cur.fetchone()["n"]

    conn.commit()

    inserted = after_count - before_count
    skipped = len(instruments) - inserted
    return inserted, skipped


def run(csv_path: str | None = None):
    path = csv_path or os.getenv("INSTRUMENTS_CSV")
    if not path:
        logger.error(
            "Missing CSV path. Pass as arg or set INSTRUMENTS_CSV env var.\n"
            "Usage: python -m data_workers.scripts.load_instruments_csv tickers.csv"
        )
        sys.exit(2)

    if not os.path.exists(path):
        logger.error("CSV file not found: %s", path)
        sys.exit(2)

    logger.info("Parsing %s...", path)
    instruments = _parse_csv(path)
    logger.info("Parsed %d rows", len(instruments))

    if not instruments:
        logger.warning("No rows to insert")
        return

    conn = DatabaseSettings().get_pg_connection()
    try:
        inserted, skipped = _bulk_upsert(conn, instruments)
        logger.info("Load complete | inserted=%d already_existed=%d", inserted, skipped)
    finally:
        conn.close()


if __name__ == "__main__":
    arg_path = sys.argv[1] if len(sys.argv) > 1 else None
    run(arg_path)
