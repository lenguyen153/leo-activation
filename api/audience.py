"""
Audience segment endpoints.

Each endpoint returns profiles matching a specific business segment definition.
All queries are read-only and routed to the production DB.

Segment logic:
  high-affinity   — has rows in product_recommendations AND in 'No Traded Profiles' CDP segment
  churn-risk      — has a portfolio account with cash_total > 10,000,000; sorted by value desc
  new-investors   — in 'New Investors' CDP segment
  active-traders  — in 'Active Traders' CDP segment
"""

import json
import logging
from typing import List, Optional

import psycopg
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from data_utils.settings import DatabaseSettings
from main_configs import REDIS_URL, RECOMMENDATION_CACHE_TTL

import redis

logger = logging.getLogger("LEO Audience API")

# ── Redis (graceful fallback) ─────────────────────────────────────────────────

_redis_client: Optional[redis.Redis] = None
try:
    if REDIS_URL:
        _redis_client = redis.from_url(REDIS_URL, decode_responses=True)
        _redis_client.ping()
except Exception:
    _redis_client = None


def _cache_get(key: str) -> Optional[str]:
    if not _redis_client:
        return None
    try:
        return _redis_client.get(key)
    except Exception:
        return None


def _cache_set(key: str, value: str) -> None:
    if not _redis_client:
        return
    try:
        _redis_client.setex(key, RECOMMENDATION_CACHE_TTL, value)
    except Exception:
        pass


# ── DB dependency (production, read-only) ────────────────────────────────────

def get_db():
    settings = DatabaseSettings()
    conn = settings.get_pg_connection_api()
    try:
        yield conn
    finally:
        conn.close()


# ── Response model ────────────────────────────────────────────────────────────

class AudienceProfileResponse(BaseModel):
    profile_id: str
    primary_email: Optional[str] = None
    cash_total: Optional[float] = None   # populated only for churn-risk segment


# ── SQL ───────────────────────────────────────────────────────────────────────

# Profiles that have product recommendations AND have not yet made any trade.
_SQL_HIGH_AFFINITY = """
    SELECT DISTINCT cp.profile_id, cp.primary_email
    FROM cdp_profiles cp
    JOIN product_recommendations pr ON pr.profile_id = cp.profile_id
    WHERE cp.segments @> jsonb_build_array(jsonb_build_object('name', 'No Traded Profiles'))
    ORDER BY cp.profile_id
    LIMIT 200
"""

# Profiles with at least one portfolio account holding > 10M cash.
# Uses the highest cash_total across all accounts per profile, sorted desc.
_SQL_CHURN_RISK = """
    SELECT cp.profile_id, cp.primary_email, p.max_cash AS cash_total
    FROM cdp_profiles cp
    JOIN (
        SELECT profile_id, MAX(cash_total) AS max_cash
        FROM portfolios
        GROUP BY profile_id
        HAVING MAX(cash_total) > 10000000
    ) p ON p.profile_id = cp.profile_id
    ORDER BY p.max_cash DESC
    LIMIT 200
"""

_SQL_NEW_INVESTORS = """
    SELECT profile_id, primary_email
    FROM cdp_profiles
    WHERE segments @> jsonb_build_array(jsonb_build_object('name', 'New Investors'))
    ORDER BY profile_id
    LIMIT 200
"""

_SQL_ACTIVE_TRADERS = """
    SELECT profile_id, primary_email
    FROM cdp_profiles
    WHERE segments @> jsonb_build_array(jsonb_build_object('name', 'Active Traders'))
    ORDER BY profile_id
    LIMIT 200
"""


# ── Helpers ───────────────────────────────────────────────────────────────────

def _run_query(conn: psycopg.Connection, sql: str) -> List[AudienceProfileResponse]:
    with conn.cursor(row_factory=psycopg.rows.dict_row) as cur:
        cur.execute(sql)
        return [AudienceProfileResponse(**row) for row in cur.fetchall()]


# ── Router ────────────────────────────────────────────────────────────────────

router = APIRouter(prefix="/audience", tags=["Audience Segments"])


@router.get("/high-affinity", response_model=List[AudienceProfileResponse])
async def get_high_affinity(conn: psycopg.Connection = Depends(get_db)):
    """
    Profiles that appear in product_recommendations AND are in the
    'No Traded Profiles' CDP segment — high intent, never converted.
    """
    cache_key = "leo:audience:high-affinity"
    try:
        cached = _cache_get(cache_key)
        if cached:
            logger.info(f"[Cache HIT] {cache_key}")
            return [AudienceProfileResponse(**r) for r in json.loads(cached)]

        logger.info(f"[Cache MISS] {cache_key}")
        results = _run_query(conn, _SQL_HIGH_AFFINITY)
        _cache_set(cache_key, json.dumps([r.model_dump() for r in results]))
        return results
    except Exception as e:
        logger.error(f"❌ High-Affinity segment error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/churn-risk", response_model=List[AudienceProfileResponse])
async def get_churn_risk(conn: psycopg.Connection = Depends(get_db)):
    """
    Profiles with portfolio cash_total > 10,000,000.
    Sorted by cash value descending — highest-value at-risk customers first.
    """
    cache_key = "leo:audience:churn-risk"
    try:
        cached = _cache_get(cache_key)
        if cached:
            logger.info(f"[Cache HIT] {cache_key}")
            return [AudienceProfileResponse(**r) for r in json.loads(cached)]

        logger.info(f"[Cache MISS] {cache_key}")
        results = _run_query(conn, _SQL_CHURN_RISK)
        _cache_set(cache_key, json.dumps([r.model_dump() for r in results]))
        return results
    except Exception as e:
        logger.error(f"❌ Churn-Risk segment error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/new-investors", response_model=List[AudienceProfileResponse])
async def get_new_investors(conn: psycopg.Connection = Depends(get_db)):
    """Profiles in the 'New Investors' CDP segment."""
    cache_key = "leo:audience:new-investors"
    try:
        cached = _cache_get(cache_key)
        if cached:
            logger.info(f"[Cache HIT] {cache_key}")
            return [AudienceProfileResponse(**r) for r in json.loads(cached)]

        logger.info(f"[Cache MISS] {cache_key}")
        results = _run_query(conn, _SQL_NEW_INVESTORS)
        _cache_set(cache_key, json.dumps([r.model_dump() for r in results]))
        return results
    except Exception as e:
        logger.error(f"❌ New-Investors segment error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/active-traders", response_model=List[AudienceProfileResponse])
async def get_active_traders(conn: psycopg.Connection = Depends(get_db)):
    """Profiles in the 'Active Traders' CDP segment."""
    cache_key = "leo:audience:active-traders"
    try:
        cached = _cache_get(cache_key)
        if cached:
            logger.info(f"[Cache HIT] {cache_key}")
            return [AudienceProfileResponse(**r) for r in json.loads(cached)]

        logger.info(f"[Cache MISS] {cache_key}")
        results = _run_query(conn, _SQL_ACTIVE_TRADERS)
        _cache_set(cache_key, json.dumps([r.model_dump() for r in results]))
        return results
    except Exception as e:
        logger.error(f"❌ Active-Traders segment error: {e}")
        raise HTTPException(status_code=500, detail=str(e))
