"""
Temporary sync: extract portfolio + holdings data from front-end
behavioral events (any event carrying `account_no`) in ArangoDB and upsert
into PostgreSQL.

Runs as a standalone script OR via Celery beat.
Will be retired once the CDC pipeline is restored.
"""
import json
import os
import re
from datetime import datetime, timezone, timedelta
from typing import Optional

from dotenv import load_dotenv

load_dotenv()

from data_utils.logging_config import configure_logging, get_logger, log_event
from data_utils.settings import DatabaseSettings
from agentic_tools.recommendation_system.interest_score import resolve_ids

configure_logging()
logger = get_logger(__name__)

# --------------------------------------------------
# Constants
# --------------------------------------------------

ACCOUNT_TYPE_MAP = {
    "1": "CASH",
    "2": "MARGIN",
    "6": "MARGIN",
    "8": "DERIVATIVES",
}

CUTOFF_DAYS = 30

# --------------------------------------------------
# AQL Query — profile_id → account_no (base) lookup from any event carrying account_no
# --------------------------------------------------

AQL_ACCOUNT_NO_LOOKUP = """
FOR event IN cdp_trackingevent
    FILTER event.createdAt >= @cutoff
    FILTER HAS(event.eventData, "account_no")
    FILTER event.eventData.account_no != null
    FILTER event.eventData.account_no != ""

    LET ref_id = (
        event.refProfileId != null AND event.refProfileId != ""
        ? event.refProfileId
        : event.fingerprintId
    )
    FILTER ref_id != null

    COLLECT
        profile_id = ref_id
    INTO grp

    LET latest = FIRST(
        FOR g IN grp
            SORT g.event.createdAt DESC
            LIMIT 1
            RETURN g.event
    )

    RETURN {
        profile_id:       profile_id,
        base_account_id:  latest.eventData.account_no,
        last_seen:        latest.createdAt
    }
"""

# --------------------------------------------------
# AQL Query — latest asset-detail-view per (current_account_id, profile)
# Provides specific account_id (with suffix) + financial property fields.
# --------------------------------------------------

AQL_ASSET_DETAIL_VIEWS = """
FOR event IN cdp_trackingevent
    FILTER event.metricName == "asset-detail-view"
    FILTER event.createdAt >= @cutoff
    FILTER HAS(event.eventData, "current_account_id")
    FILTER event.eventData.current_account_id != null
    FILTER event.eventData.current_account_id != ""

    SORT event.createdAt DESC

    COLLECT
        account_id = event.eventData.current_account_id
    INTO grp

    LET latest_event = FIRST(
        FOR g IN grp
            SORT g.event.createdAt DESC
            LIMIT 1
            RETURN g.event
    )
    LET latest = latest_event.eventData
    LET ref_id  = (
        latest_event.refProfileId != null AND latest_event.refProfileId != ""
        ? latest_event.refProfileId
        : latest_event.fingerprintId
    )

    RETURN {
        account_id:       account_id,
        base_account_id:  latest.account_no,
        profile_id:       ref_id,
        nav:              latest.nav,
        cash_total:       latest.cash_total,
        debt_total:       latest.debt_total,
        collaterals:      latest.collaterals,
        margin_limit:     latest.margin_limit,
        pnl:              latest.PNL,
        rtt:              latest.RTT,
        holdings:         latest.holdings,
        asset_allocation: latest.asset_allocation,
        last_seen:        grp[0].event.createdAt
    }
"""

# --------------------------------------------------
# SQL UPSERTs
# --------------------------------------------------

UPSERT_PORTFOLIO_SQL = """
INSERT INTO portfolios (
    tenant_id, account_id, base_account_id, account_type, account_suffix,
    profile_id, nav, cash_total, debt_total, collaterals, margin_limit, pnl,
    rtt_ratio, asset_allocation, source_timestamp
)
VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s::jsonb, %s)
ON CONFLICT (tenant_id, account_id) DO UPDATE SET
    base_account_id  = EXCLUDED.base_account_id,
    nav              = EXCLUDED.nav,
    cash_total       = EXCLUDED.cash_total,
    debt_total       = EXCLUDED.debt_total,
    collaterals      = EXCLUDED.collaterals,
    margin_limit     = EXCLUDED.margin_limit,
    pnl              = EXCLUDED.pnl,
    rtt_ratio        = EXCLUDED.rtt_ratio,
    asset_allocation = EXCLUDED.asset_allocation,
    source_timestamp = EXCLUDED.source_timestamp,
    updated_at       = now()
WHERE portfolios.source_timestamp IS NULL
   OR EXCLUDED.source_timestamp > portfolios.source_timestamp;
"""

UPSERT_HOLDING_SQL = """
INSERT INTO portfolio_holdings (
    tenant_id, account_id, symbol, quantity, avg_price, current_price, source_timestamp
)
VALUES (%s, %s, %s, %s, %s, %s, %s)
ON CONFLICT (tenant_id, account_id, symbol) DO UPDATE SET
    quantity         = EXCLUDED.quantity,
    avg_price        = EXCLUDED.avg_price,
    current_price    = EXCLUDED.current_price,
    source_timestamp = EXCLUDED.source_timestamp,
    updated_at       = now()
WHERE portfolio_holdings.source_timestamp IS NULL
   OR EXCLUDED.source_timestamp > portfolio_holdings.source_timestamp;
"""

UPDATE_PROFILE_EXT_DATA_SQL = """
UPDATE cdp_profiles
SET ext_data = COALESCE(ext_data, '{}'::jsonb)
             || jsonb_build_object('base_account_id', %s::text)
WHERE profile_id = %s;
"""

# --------------------------------------------------
# Transform helpers
# --------------------------------------------------


def parse_account_suffix(raw_account_id: str) -> dict:
    """
    Extract suffix + account_type from the trailing character of a specific
    account_id (e.g. "999C0000171" → suffix="1", type="CASH").
    Does NOT derive base_account_id — that now comes from the account_no field.
    """
    raw = str(raw_account_id).strip()
    if len(raw) < 2:
        return {"account_id": raw, "account_suffix": "0", "account_type": "UNKNOWN"}
    suffix = raw[-1]
    return {
        "account_id": raw,
        "account_suffix": suffix,
        "account_type": ACCOUNT_TYPE_MAP.get(suffix, "UNKNOWN"),
    }


def parse_locale_number(val, default=0) -> float:
    """
    Parse Vietnamese locale-formatted numbers from the FE.
    "96.690.000" → 96690000.0   (dots are thousands separators)
    "-"  → 0                    (dash means empty)
    "-%"  → 0
    0    → 0
    """
    if val is None:
        return default
    if isinstance(val, (int, float)):
        return float(val)
    s = str(val).strip()
    if not s or s in ("-", "-%", ""):
        return default
    # Remove % suffix if present
    s = s.rstrip("%").strip()
    # Remove dots used as thousands separator (Vietnamese locale)
    # But keep comma as decimal separator, then swap
    s = s.replace(".", "")
    s = s.replace(",", ".")
    try:
        return float(s)
    except (ValueError, TypeError):
        return default


def parse_holdings_string(holdings_raw) -> list[dict]:
    """
    Parse the FE holdings JSON string into a list of {symbol, allocation_pct}.
    Input:  '["AAS - 100%","BCM - 40%","CEO - 12%"]'
    Output: [{"symbol": "AAS", "pct": 100.0}, {"symbol": "BCM", "pct": 40.0}, ...]
    """
    if not holdings_raw:
        return []
    try:
        items = json.loads(holdings_raw) if isinstance(holdings_raw, str) else holdings_raw
    except (json.JSONDecodeError, TypeError):
        return []
    results = []
    for item in items:
        match = re.match(r"^([A-Za-z0-9]+)\s*-\s*([\d.]+)%?$", str(item).strip())
        if match:
            results.append({
                "symbol": match.group(1).upper(),
                "pct": float(match.group(2)),
            })
    return results


def parse_asset_allocation(alloc_raw) -> dict:
    """
    Parse FE asset_allocation string into a JSONB-ready dict.
    Input:  '["cash - 92%","stock - 8%","futures - 0%"]'
    Output: {"cash": 0.92, "stock": 0.08, "futures": 0.0}
    """
    if not alloc_raw:
        return {}
    try:
        items = json.loads(alloc_raw) if isinstance(alloc_raw, str) else alloc_raw
    except (json.JSONDecodeError, TypeError):
        return {}
    result = {}
    for item in items:
        match = re.match(r"^([A-Za-z_]+)\s*-\s*([\d.]+)%?$", str(item).strip())
        if match:
            result[match.group(1).lower()] = float(match.group(2)) / 100.0
    return result


# --------------------------------------------------
# Row builders
# --------------------------------------------------


def _build_portfolio_rows(events, tenant_id, valid_pids):
    """
    One row per specific account_id (from asset-detail-view).
    base_account_id is taken directly from the event's account_no field.
    AQL already sorted DESC, first seen = latest.
    """
    seen = {}
    for evt in events:
        pid = evt.get("profile_id")
        aid = str(evt.get("account_id", "")).strip()
        base_account_id = str(evt.get("base_account_id") or "").strip()

        if pid not in valid_pids or not aid or not base_account_id:
            continue
        if aid in seen:
            continue

        parsed = parse_account_suffix(aid)
        alloc = parse_asset_allocation(evt.get("asset_allocation"))

        seen[aid] = (
            tenant_id,
            parsed["account_id"],
            base_account_id,
            parsed["account_type"],
            parsed["account_suffix"],
            pid,
            parse_locale_number(evt.get("nav")),
            parse_locale_number(evt.get("cash_total")),
            parse_locale_number(evt.get("debt_total")),
            parse_locale_number(evt.get("collaterals")),
            parse_locale_number(evt.get("margin_limit")),
            parse_locale_number(evt.get("pnl")),
            parse_locale_number(evt.get("rtt")) or None,  # NULL if 0
            json.dumps(alloc),
            evt.get("last_seen"),
        )
    return list(seen.values())


def _build_holding_rows(events, tenant_id, valid_pids, valid_account_ids):
    """Parse the holdings JSON string from each event into individual rows."""
    seen = {}
    for evt in events:
        pid = evt.get("profile_id")
        aid = str(evt.get("account_id", "")).strip()
        if pid not in valid_pids or aid not in valid_account_ids:
            continue

        holdings = parse_holdings_string(evt.get("holdings"))
        last_seen = evt.get("last_seen")

        for h in holdings:
            key = (aid, h["symbol"])
            if key in seen:
                continue
            seen[key] = (
                tenant_id,
                aid,
                h["symbol"],
                0,           # quantity — not available in FE events
                0,           # avg_price — not available in FE events
                0,           # current_price — not available in FE events
                last_seen,
            )
    return list(seen.values())


# --------------------------------------------------
# Upsert executors
# --------------------------------------------------


def _upsert_portfolios(conn, rows: list) -> int:
    if not rows:
        return 0
    with conn.cursor() as cur:
        cur.executemany(UPSERT_PORTFOLIO_SQL, rows)
    return len(rows)


def _upsert_holdings(conn, rows: list) -> int:
    if not rows:
        return 0
    with conn.cursor() as cur:
        cur.executemany(UPSERT_HOLDING_SQL, rows)
    return len(rows)


def _update_profile_base_account_ids(conn, base_by_pid: dict, valid_pids: set) -> int:
    """Write {base_account_id: <id>} into cdp_profiles.ext_data jsonb."""
    rows = [(base, pid) for pid, base in base_by_pid.items() if pid in valid_pids]
    if not rows:
        return 0
    with conn.cursor() as cur:
        cur.executemany(UPDATE_PROFILE_EXT_DATA_SQL, rows)
    return len(rows)


# --------------------------------------------------
# Core orchestrator
# --------------------------------------------------


def sync_active_users_portfolios(
    *,
    tenant_name: Optional[str] = None,
    segment_name: Optional[str] = None,
) -> dict:
    """
    Sync flow:
      - Any event carrying `account_no` → maps profile_id to base_account_id;
        written to both cdp_profiles.ext_data and portfolios.base_account_id.
      - asset-detail-view events → upsert portfolios row with specific account_id
        (current_account_id) and financial property fields.
    Returns {"portfolios", "holdings", "profiles_updated", "skipped"}.
    """
    tenant_name = tenant_name or os.getenv("TARGET_TENANT", "master")
    segment_name = segment_name or os.getenv("TARGET_SEGMENT", "Active in last 3 months")

    settings = DatabaseSettings()
    conn = settings.get_pg_connection()

    try:
        # 1. Resolve tenant
        tenant_uuid, _ = resolve_ids(conn, tenant_name, segment_name)
        tenant_id = str(tenant_uuid)

        # 2. Extract from ArangoDB (createdAt is ISO 8601 string)
        cutoff = (datetime.now(timezone.utc) - timedelta(days=CUTOFF_DAYS)).strftime("%Y-%m-%dT%H:%M:%S.000Z")
        db = settings.get_arango_db()

        account_no_rows = list(db.aql.execute(AQL_ACCOUNT_NO_LOOKUP, bind_vars={"cutoff": cutoff}))
        logger.info("Fetched %d account_no lookup rows from ArangoDB", len(account_no_rows))

        detail_events = list(db.aql.execute(AQL_ASSET_DETAIL_VIEWS, bind_vars={"cutoff": cutoff}))
        logger.info("Fetched %d asset-detail-view rows from ArangoDB", len(detail_events))

        if not account_no_rows and not detail_events:
            logger.info("No events found. Nothing to sync.")
            return {"portfolios": 0, "holdings": 0, "profiles_updated": 0, "skipped": 0}

        base_by_pid = {
            r["profile_id"]: r["base_account_id"]
            for r in account_no_rows
            if r.get("profile_id") and r.get("base_account_id")
        }

        # 3. Filter — orphan isolation against PG cdp_profiles
        all_profile_ids = list(
            {r["profile_id"] for r in account_no_rows if r.get("profile_id")}
            | {e["profile_id"] for e in detail_events if e.get("profile_id")}
        )
        with conn.cursor() as cur:
            cur.execute(
                "SELECT profile_id FROM cdp_profiles WHERE profile_id = ANY(%s)",
                (all_profile_ids,),
            )
            valid_pids = {row["profile_id"] for row in cur.fetchall()}

        skipped = len(all_profile_ids) - len(valid_pids)
        if skipped:
            logger.warning("Skipping %d orphaned profile(s) not in cdp_profiles", skipped)

        # 4. Write base_account_id into cdp_profiles.ext_data
        profiles_updated = _update_profile_base_account_ids(conn, base_by_pid, valid_pids)

        # 5. Drop stale portfolio rows for profiles in this sync run.
        #    Old rows may have been keyed on a wrong account_id (derived by stripping
        #    the last digit), so ON CONFLICT won't match them — delete first.
        synced_pids = list(valid_pids & base_by_pid.keys())
        if synced_pids:
            with conn.cursor() as cur:
                cur.execute(
                    "DELETE FROM portfolios WHERE tenant_id = %s AND profile_id = ANY(%s)",
                    (tenant_id, synced_pids),
                )
            logger.info("Cleared stale portfolio rows for %d profiles", len(synced_pids))

        # 6. Transform + Load portfolios (one row per specific account_id)
        portfolio_rows = _build_portfolio_rows(detail_events, tenant_id, valid_pids)
        p_count = _upsert_portfolios(conn, portfolio_rows)

        # 7. Transform + Load holdings (FK-safe: only accounts from step 6)
        valid_account_ids = {row[1] for row in portfolio_rows}
        holding_rows = _build_holding_rows(detail_events, tenant_id, valid_pids, valid_account_ids)
        h_count = _upsert_holdings(conn, holding_rows)

        conn.commit()
        log_event(logger, "portfolio_sync_complete",
                  account_rows=len(account_no_rows), detail_events=len(detail_events),
                  skipped=skipped, stale_cleared=len(synced_pids),
                  portfolios=p_count, holdings=h_count, profiles=profiles_updated)
        return {
            "portfolios": p_count,
            "holdings": h_count,
            "profiles_updated": profiles_updated,
            "skipped": skipped,
        }

    except Exception as exc:
        conn.rollback()
        logger.exception("Portfolio sync failed")
        raise exc
    finally:
        conn.close()


# --------------------------------------------------
# CLI entry point
# --------------------------------------------------

if __name__ == "__main__":
    result = sync_active_users_portfolios()
    log_event(logger, "sync_active_users_portfolios_done", **result)
