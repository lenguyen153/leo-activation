"""Portfolio API endpoints for LEO Activation."""

import json
import logging
from typing import List, Optional

import psycopg
import redis
from fastapi import APIRouter, HTTPException, Query, Depends
from pydantic import BaseModel

from data_utils.settings import DatabaseSettings
from main_configs import REDIS_URL, RECOMMENDATION_CACHE_TTL

logger = logging.getLogger("LEO Portfolio API")

# --- REDIS CACHE (module-level singleton, graceful fallback) ---
_redis_client: Optional[redis.Redis] = None
try:
    if REDIS_URL:
        _redis_client = redis.from_url(REDIS_URL, decode_responses=True)
        _redis_client.ping()
        logger.info("Redis cache connected for portfolio endpoints.")
    else:
        logger.warning("REDIS_URL not set. Portfolio caching disabled.")
except Exception as e:
    logger.warning(f"Redis unavailable — portfolio caching disabled. {e}")
    _redis_client = None


def _cache_get(key: str) -> Optional[str]:
    if not _redis_client:
        return None
    try:
        return _redis_client.get(key)
    except Exception as e:
        logger.error(f"Redis read error: {e}")
        return None


def _cache_set(key: str, value: str) -> None:
    if not _redis_client:
        return
    try:
        _redis_client.setex(key, RECOMMENDATION_CACHE_TTL, value)
    except Exception as e:
        logger.error(f"Redis write error: {e}")

# --- ROUTER SETUP ---
router = APIRouter(
    prefix="/portfolio",
    tags=["Portfolio"],
)


# --- DEPENDENCIES ---
def get_db():
    settings = DatabaseSettings()
    conn = settings.get_pg_connection()
    try:
        yield conn
    finally:
        conn.close()


# --- DATA MODELS ---
class PortfolioUserResponse(BaseModel):
    profile_id: str
    primary_email: Optional[str] = None
    base_account_id: Optional[str] = None


# --- SQL ---
_SQL_LOOKUP_USER = """
    SELECT DISTINCT
        p.profile_id,
        p.primary_email,
        pt.base_account_id
    FROM cdp_profiles p
    LEFT JOIN portfolios pt ON pt.profile_id = p.profile_id
    WHERE (p.primary_email = %s OR p.profile_id = %s OR pt.base_account_id = %s)
"""

_SQL_LOOKUP_USER_SEGMENT = _SQL_LOOKUP_USER + """
    AND EXISTS (
        SELECT 1 FROM jsonb_array_elements(p.segments) AS s
        WHERE s->>'name' = ANY(%s)
    )
"""

_SEGMENT_MAP = {
    "uat": ["UAT 1invest Users"],
    "prod": ["Production 1invest Users"],
}
_SEGMENT_ALL = ["UAT 1invest Users", "Production 1invest Users"]


# --- HELPERS ---

def _backfill_base_account_id(results: list) -> None:
    """
    CDP can have duplicate profiles with the same email.
    Only one may have a portfolio row (and thus a base_account_id).
    Propagate it to siblings that share the same primary_email.
    """
    # Build email → base_account_id map from rows that have it
    email_to_base = {}
    for r in results:
        if r.base_account_id and r.primary_email:
            email_to_base.setdefault(r.primary_email, r.base_account_id)

    # Fill nulls from siblings
    for r in results:
        if not r.base_account_id and r.primary_email:
            r.base_account_id = email_to_base.get(r.primary_email)


# --- ENDPOINTS ---
@router.get("/user", response_model=List[PortfolioUserResponse])
async def get_portfolio_user(
    lookup: str = Query(
        ...,
        description="Search value: email, profile_id, or base_account_id",
    ),
    env: Optional[str] = Query(
        None,
        description="Filter by environment: 'uat', 'prod', or omit for all",
        enum=["uat", "prod"],
    ),
    conn: psycopg.Connection = Depends(get_db),
):
    """
    Look up a user by email, profile_id, or base_account_id.
    Returns profile_id, primary_email, and base_account_id.
    - **uat**: UAT 1invest Users only
    - **prod**: Production 1invest Users only
    - **omit**: no segment filter
    """
    try:
        cache_key = f"leo:portfolio:users:{lookup}:{env or 'all'}"
        cached = _cache_get(cache_key)
        if cached:
            logger.info(f"[Cache HIT] {cache_key}")
            return [PortfolioUserResponse(**r) for r in json.loads(cached)]

        logger.info(f"[Cache MISS] {cache_key}")
        with conn.cursor(row_factory=psycopg.rows.dict_row) as cur:
            if env:
                segments = _SEGMENT_MAP[env]
                cur.execute(_SQL_LOOKUP_USER_SEGMENT, (lookup, lookup, lookup, segments))
            else:
                cur.execute(_SQL_LOOKUP_USER, (lookup, lookup, lookup))
            rows = cur.fetchall()
        results = [PortfolioUserResponse(**r) for r in rows]

        # Backfill: if sibling profiles share the same email,
        # propagate base_account_id from the one that has it
        _backfill_base_account_id(results)

        _cache_set(cache_key, json.dumps([r.model_dump() for r in results]))
        return results
    except Exception as e:
        logger.error("Portfolio user lookup failed: %s", e)
        raise HTTPException(status_code=500, detail=str(e))
