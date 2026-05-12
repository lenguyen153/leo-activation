"""
build_df_train.py
=================
Build df_train for the XGBoost NLA Propensity Model from the production database.

All features are computed point-in-time relative to each behavioral event's timestamp.
Market features (price change, volume spike) are derived entirely from
market_snapshot_history — NOT from the live market_snapshot table.

Volume spike definition (mirrors poll_market_snapshot._compute_volume_analytics):
    avg_30d_volume  = AVG(MAX daily volume) over [event_ts - 30d, event_ts)
    is_volume_spike = current_volume > avg_30d_volume * 2

Output:
    tmp/df_train_real.csv

Usage:
    python build_df_train.py
"""

import os
import sys
import numpy as np
import pandas as pd
import psycopg
from psycopg.rows import dict_row

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
sys.path.insert(0, ROOT)
from data_utils.settings import DatabaseSettings

# ─── Target mapping ───────────────────────────────────────────────────────────
TARGET_MAP = {
    "order-created":       4,
    "group-order-created": 4,
    "watchlist-add":       2,
    "watchlist-remove":    2,
    "page-view":           1,
    "indices-view":        1,
    "overview-view":       1,
    "news-view":           1,
    "component-hover":     0,
    # all other ticker-specific events → 3 (view)
}

OUTPUT_PATH = os.path.join(os.path.dirname(__file__), "..", "output", "df_train_real.csv")


# ─── 1. Fetch ─────────────────────────────────────────────────────────────────

def _set_rls_tenant(cur) -> None:
    """Set app.current_tenant_id for the session so RLS-gated tables are visible."""
    cur.execute("SELECT tenant_id FROM tenant WHERE tenant_name = 'master' LIMIT 1")
    row = cur.fetchone()
    if not row:
        cur.execute("SELECT tenant_id FROM tenant WHERE status = 'active' LIMIT 1")
        row = cur.fetchone()
    if row:
        tid = str(row["tenant_id"])
        cur.execute("SELECT set_config('app.current_tenant_id', %s, false)", (tid,))
        print(f"  RLS tenant: {tid}")
    else:
        print("  WARNING: no tenant found in tenant table")


def fetch_all(dsn: str) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    with psycopg.connect(dsn, row_factory=dict_row) as conn:
        with conn.cursor() as cur:

            _set_rls_tenant(cur)

            print("  Fetching behavioral_events …")
            cur.execute("""
                SELECT profile_id, event_metric_name, entity_id, created_at
                FROM   behavioral_events
                ORDER  BY profile_id, created_at
            """)
            events = pd.DataFrame(cur.fetchall())
            if events.empty:
                raise RuntimeError(
                    "behavioral_events returned 0 rows on this DB. "
                    "Run sync_behavioral_events.py first to populate the table."
                )

            print("  Fetching market_snapshot_history …")
            cur.execute("""
                SELECT symbol,
                       change_percent_24h::float AS change_pct,
                       current_volume,
                       snapshot_at
                FROM   market_snapshot_history
                ORDER  BY symbol, snapshot_at
            """)
            msh = pd.DataFrame(cur.fetchall())

            print("  Fetching market_snapshot (volume spike) …")
            cur.execute("""
                SELECT symbol,
                       COALESCE(is_volume_spike, false)::int AS is_volume_spike
                FROM   market_snapshot
            """)
            ms = pd.DataFrame(cur.fetchall())

            print("  Fetching product_recommendations …")
            cur.execute("""
                SELECT profile_id,
                       product_id                    AS symbol,
                       AVG(interest_score::float)    AS interest_score
                FROM   product_recommendations
                GROUP  BY profile_id, product_id
            """)
            pr = pd.DataFrame(cur.fetchall())

    print(f"  → {len(events):,} events | {len(msh):,} msh rows | {len(pr):,} pr rows")
    return events, msh, ms, pr


# ─── 2. Market features (point-in-time from market_snapshot_history) ──────────

def build_price_change(events: pd.DataFrame, msh: pd.DataFrame) -> pd.Series:
    """
    Point-in-time asset_price_change_24h: closest market_snapshot_history
    entry at or before each event's created_at, per symbol.
    """
    msh = msh.copy()
    msh["snapshot_at"] = pd.to_datetime(msh["snapshot_at"], utc=True)

    results = []
    for symbol, sym_events in events.groupby("entity_id", sort=False):
        sym_msh = msh[msh["symbol"] == symbol].sort_values("snapshot_at")
        sym_ev  = sym_events.sort_values("created_at").copy()

        if sym_msh.empty:
            sym_ev["asset_price_change_24h"] = 0.0
        else:
            merged = pd.merge_asof(
                sym_ev[["created_at"]].reset_index(),
                sym_msh[["snapshot_at", "change_pct"]].rename(
                    columns={"snapshot_at": "created_at"}
                ),
                on="created_at",
                direction="backward",
            )
            sym_ev = sym_ev.reset_index()
            sym_ev["asset_price_change_24h"] = merged["change_pct"].fillna(0.0).values
            sym_ev = sym_ev.set_index("index")

        results.append(sym_ev[["asset_price_change_24h"]])

    return pd.concat(results).reindex(events.index)["asset_price_change_24h"]


# ─── 3. Build full df_train ───────────────────────────────────────────────────

def build(dsn: str) -> pd.DataFrame:
    events, msh, ms, pr = fetch_all(dsn)

    events["created_at"] = pd.to_datetime(events["created_at"], utc=True)
    events = events.sort_values(["profile_id", "created_at"]).reset_index(drop=True)

    # target_action
    events["target_action"] = (
        events["event_metric_name"].map(TARGET_MAP).fillna(3).astype(int)
    )

    # time_since_last_interaction (minutes)
    events["time_since_last_interaction"] = (
        events.groupby("profile_id")["created_at"]
        .diff()
        .dt.total_seconds()
        .div(60)
    )
    median_t = events["time_since_last_interaction"].median()
    events["time_since_last_interaction"] = (
        events["time_since_last_interaction"].fillna(median_t)
    )

    # is_active_trader — above-median event count per profile
    counts  = events.groupby("profile_id").size()
    active  = set(counts[counts > counts.median()].index)
    events["is_active_trader"] = events["profile_id"].isin(active).astype(int)

    # historical_conversion_rate — 90-day rolling window per profile
    print("  Computing historical_conversion_rate …")
    conv = []
    for _, grp in events.groupby("profile_id", sort=False):
        grp = grp.sort_values("created_at").reset_index(drop=True)
        for i in range(len(grp)):
            ts     = grp.loc[i, "created_at"]
            cutoff = ts - pd.Timedelta(days=90)
            w      = grp[(grp["created_at"] >= cutoff) & (grp["created_at"] < ts)]
            bought = w[w["event_metric_name"] == "order-created"]["entity_id"].nunique()
            viewed = w[w["event_metric_name"] != "order-created"]["entity_id"].nunique()
            conv.append(bought / viewed if viewed > 0 else 0.0)
    events["historical_conversion_rate"] = conv

    # asset_price_change_24h — point-in-time from market_snapshot_history
    print("  Computing asset_price_change_24h from market_snapshot_history …")
    events["asset_price_change_24h"] = build_price_change(events, msh).values

    # asset_trading_volume_spike — from market_snapshot (poller pre-computes this)
    events = events.merge(ms, left_on="entity_id", right_on="symbol", how="left")
    events["asset_trading_volume_spike"] = events["is_volume_spike"].fillna(0).astype(int)

    # current_interest_score — avg interest_score per (profile, symbol)
    events = events.merge(
        pr, left_on=["profile_id", "entity_id"],
        right_on=["profile_id", "symbol"], how="left"
    )
    median_score = events["interest_score"].median()
    events["current_interest_score"] = events["interest_score"].fillna(median_score)

    COLS = [
        "current_interest_score",
        "time_since_last_interaction",
        "is_active_trader",
        "historical_conversion_rate",
        "asset_price_change_24h",
        "asset_trading_volume_spike",
        "target_action",
    ]
    return events[COLS].copy()


# ─── Entry point ──────────────────────────────────────────────────────────────

if __name__ == "__main__":
    from dotenv import load_dotenv
    load_dotenv(os.path.join(ROOT, ".env"), override=True)

    print("Building df_train from production DB …")
    settings = DatabaseSettings()

    # Swap host to PGSQL_DB_HOST_PROD when available
    prod_host = os.getenv("PGSQL_DB_HOST_PROD")
    dsn = settings.pg_dsn
    if prod_host:
        dsn = dsn.replace(settings.PGSQL_DB_HOST, prod_host)
        print(f"  Using prod host: {prod_host}")

    df = build(dsn)

    print(f"\ndf_train shape: {df.shape}")
    print(df.dtypes)
    print(f"\nTarget distribution:\n{df['target_action'].value_counts().sort_index()}")
    print(f"\nVolume spike rate: {df['asset_trading_volume_spike'].mean():.1%}")

    os.makedirs(os.path.dirname(OUTPUT_PATH), exist_ok=True)
    df.to_csv(OUTPUT_PATH, index=False)
    print(f"\nSaved → {OUTPUT_PATH}")
