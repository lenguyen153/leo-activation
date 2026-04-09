"""PostgreSQL read/write for incremental score upserts."""

import datetime
import logging
from urllib.parse import quote_plus

import psycopg
from psycopg.rows import dict_row

from services.scoring_consumer.config import (
    PGSQL_DB_HOST,
    PGSQL_DB_NAME,
    PGSQL_DB_PASSWORD,
    PGSQL_DB_PORT,
    PGSQL_DB_USER,
)

logger = logging.getLogger(__name__)

# Reuse the same dummy PK values as batch scoring
DUMMY_JOURNEY_MAP_ID = "default_journey_map"
DUMMY_JOURNEY_STAGE_ID = "default_stage"
DUMMY_REC_MODEL = "default_model"
DUMMY_PRODUCT_TYPE = "stock"

_SELECT_SQL = """
    SELECT raw_score, interest_score, last_interaction_at
    FROM product_recommendations
    WHERE profile_id = %s
      AND product_id = %s
      AND product_type = %s
      AND tenant_id = %s
      AND journey_map_id = %s
      AND journey_stage_id = %s
      AND recommendation_model = %s
"""

_UPSERT_SQL = """
    INSERT INTO product_recommendations (
        tenant_id, profile_id, product_id, product_type,
        journey_map_id, journey_stage_id, recommendation_model,
        raw_score, interest_score, last_interaction_at, updated_at,
        recommendation_context,
        product_url, rank_position,
        model_version, reason_codes
    )
    VALUES (
        %s, %s, %s, %s,
        %s, %s, %s,
        %s, %s, %s, NOW(),
        NULL,
        NULL, NULL,
        NULL, NULL
    )
    ON CONFLICT (tenant_id, profile_id, journey_map_id, journey_stage_id, product_id, recommendation_model)
    DO UPDATE SET
        raw_score = EXCLUDED.raw_score,
        interest_score = EXCLUDED.interest_score,
        last_interaction_at = EXCLUDED.last_interaction_at,
        updated_at = NOW();
"""


def _build_dsn() -> str:
    encoded_pw = quote_plus(PGSQL_DB_PASSWORD)
    return (
        f"postgresql://{PGSQL_DB_USER}:{encoded_pw}@"
        f"{PGSQL_DB_HOST}:{PGSQL_DB_PORT}/"
        f"{PGSQL_DB_NAME}?options=-c%20search_path%3Dag_catalog,public"
    )


_conn: psycopg.Connection | None = None


def get_connection() -> psycopg.Connection:
    """Get PG connection, reconnecting if stale or closed."""
    global _conn
    if _conn is None or _conn.closed:
        logger.info("Opening new PG connection to %s:%s/%s", PGSQL_DB_HOST, PGSQL_DB_PORT, PGSQL_DB_NAME)
        _conn = psycopg.connect(_build_dsn(), row_factory=dict_row, autocommit=False)
    return _conn


def reset_connection() -> psycopg.Connection:
    """Force close and reopen PG connection (call after connection errors)."""
    global _conn
    if _conn is not None:
        try:
            _conn.close()
        except Exception:
            pass
        _conn = None
    return get_connection()


def fetch_existing_score(conn, tenant_id: str, profile_id: str, ticker: str) -> dict | None:
    """Fetch current score row. Returns dict with raw_score, interest_score, last_interaction_at or None."""
    with conn.cursor() as cur:
        cur.execute(_SELECT_SQL, (
            profile_id, ticker, DUMMY_PRODUCT_TYPE, tenant_id,
            DUMMY_JOURNEY_MAP_ID, DUMMY_JOURNEY_STAGE_ID, DUMMY_REC_MODEL,
        ))
        return cur.fetchone()


def upsert_score(
    conn,
    tenant_id: str,
    profile_id: str,
    ticker: str,
    raw_score: float,
    interest_score: float,
    last_event_time: datetime.datetime,
) -> None:
    """Insert or update the product_recommendations row."""
    with conn.cursor() as cur:
        cur.execute(_UPSERT_SQL, (
            tenant_id, profile_id, ticker, DUMMY_PRODUCT_TYPE,
            DUMMY_JOURNEY_MAP_ID, DUMMY_JOURNEY_STAGE_ID, DUMMY_REC_MODEL,
            raw_score, interest_score, last_event_time,
        ))
    conn.commit()


def validate_profile(conn, profile_id: str) -> bool:
    """Check that profile_id exists in cdp_profiles."""
    with conn.cursor() as cur:
        cur.execute("SELECT 1 FROM cdp_profiles WHERE profile_id = %s LIMIT 1", (profile_id,))
        return cur.fetchone() is not None


def fetch_base_account_id(conn, profile_id: str) -> str | None:
    """Resolve profile_id → base_account_id via the portfolios table."""
    with conn.cursor() as cur:
        cur.execute(
            "SELECT base_account_id FROM portfolios WHERE profile_id = %s LIMIT 1",
            (profile_id,),
        )
        row = cur.fetchone()
        return row["base_account_id"] if row else None
