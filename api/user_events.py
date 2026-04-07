"""
API endpoint: Top Significant Events for a user.

Fetches a normalized, truncated list of the top events for a specific user,
identified by base_account_id, email, or profile_id. Events are ranked by a
strict event-type priority, then by recency.
"""

import json
import logging
import time
from typing import List, Optional

import psycopg
import redis
from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from data_utils.settings import DatabaseSettings
from main_configs import REDIS_URL, RECOMMENDATION_CACHE_TTL

logger = logging.getLogger("LEO User Events API")

# --- REDIS CACHE (module-level singleton, graceful fallback) ---
_redis_client: Optional[redis.Redis] = None
try:
    if REDIS_URL:
        _redis_client = redis.from_url(REDIS_URL, decode_responses=True)
        _redis_client.ping()
        logger.info("Redis cache connected for user-events endpoints.")
    else:
        logger.warning("REDIS_URL not set. User-events caching disabled.")
except Exception as e:
    logger.warning(f"Redis unavailable — user-events caching disabled. {e}")
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
        logger.warning(f"[Cache SKIP] Redis client is None, cannot cache {key}")
        return
    try:
        _redis_client.setex(key, RECOMMENDATION_CACHE_TTL, value)
        logger.info(f"[Cache SET] {key} (TTL={RECOMMENDATION_CACHE_TTL}s)")
    except Exception as e:
        logger.error(f"Redis write error: {e}")

# --- ROUTER SETUP ---
router = APIRouter(
    prefix="/user-events",
    tags=["User Events"],
)

# --- CONSTANTS ---

# Priority ranking: lower index = higher priority
_PRIORITY_METRICS = [
    "order-created",
    "group-order-created",
    "order-preview",
    "order-quitted",
    "order-canceled",
    "search",
    "watchlist-add",
    "ticker-view",
    "watchlist-view",
]

_PRIORITY_MAP = {name: idx for idx, name in enumerate(_PRIORITY_METRICS)}
_FALLBACK_PRIORITY = len(_PRIORITY_METRICS)  # for any other event with instrument IDs
_THREE_MONTHS_SECONDS = 90 * 24 * 3600  # ~3 months in seconds


# --- DATA MODELS ---

class TopEventItem(BaseModel):
    metricName: str
    instrumentIds: List[str] = Field(default_factory=list)
    createdAt: List[float] = Field(default_factory=list)


# --- HELPERS ---

def _get_arango_db():
    settings = DatabaseSettings()
    return settings.get_arango_db()


def _get_pg_connection() -> psycopg.Connection:
    settings = DatabaseSettings()
    return settings.get_pg_connection()


def _resolve_profile_id_from_account(base_account_id: str) -> Optional[str]:
    """Resolve base_account_id → profile_id via PG portfolios table."""
    conn = _get_pg_connection()
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT profile_id FROM portfolios WHERE base_account_id = %s LIMIT 1",
                (base_account_id.strip(),),
            )
            row = cur.fetchone()
            if not row:
                logger.warning(f"No portfolio found for base_account_id={base_account_id}")
                return None
            pid = row["profile_id"] if isinstance(row, dict) else row[0]
            logger.info(f"Resolved base_account_id={base_account_id} → profile_id={pid}")
            return pid
    finally:
        conn.close()


def _resolve_fingerprints_by_email(db, email: str) -> List[str]:
    """Resolve email → fingerprintId(s) via ArangoDB cdp_profile."""
    aql = """
        FOR p IN cdp_profile
            FILTER p.primaryEmail == @email
            RETURN p.fingerprintId
    """
    cursor = db.aql.execute(aql, bind_vars={"email": email.strip()})
    return [fp for fp in cursor if fp]


# Query events by refProfileId (for profile_id / base_account_id lookups)
_AQL_TOP_EVENTS_BY_PROFILE = """
FOR event IN cdp_trackingevent
    FILTER event.refProfileId == @profile_id
    FILTER event.eventData.timestamp != null
    FILTER event.eventData.timestamp >= @cutoff_ts

    LET single = event.eventData.instrument_id
    LET list   = event.eventData.instrument_id_list
    LET ids = (
        single != null AND single != ""
        ? [single]
        : (IS_ARRAY(list) AND LENGTH(list) > 0 ? list : [])
    )

    FILTER LENGTH(ids) > 0
    FILTER event.metricName IN @priority_metrics OR LENGTH(ids) > 0

    RETURN {
        metricName:  event.metricName,
        instrumentIds: ids,
        createdAt:   event.eventData.timestamp
    }
"""

# Query events by fingerprintId (for email lookups)
_AQL_TOP_EVENTS_BY_FINGERPRINT = """
FOR event IN cdp_trackingevent
    FILTER event.fingerprintId IN @fingerprints
    FILTER event.eventData.timestamp != null
    FILTER event.eventData.timestamp >= @cutoff_ts

    LET single = event.eventData.instrument_id
    LET list   = event.eventData.instrument_id_list
    LET ids = (
        single != null AND single != ""
        ? [single]
        : (IS_ARRAY(list) AND LENGTH(list) > 0 ? list : [])
    )

    FILTER LENGTH(ids) > 0
    FILTER event.metricName IN @priority_metrics OR LENGTH(ids) > 0

    RETURN {
        metricName:  event.metricName,
        instrumentIds: ids,
        createdAt:   event.eventData.timestamp
    }
"""


def _sort_and_truncate(events: list, top_k: int) -> List[TopEventItem]:
    """Group by (metricName, instrumentIds), sort by priority ASC then latest createdAt DESC, truncate to topK."""
    # Group events by (metricName, sorted instrumentIds)
    groups: dict[tuple, dict] = {}
    for e in events:
        ids = e.get("instrumentIds") or []
        key = (e["metricName"], tuple(sorted(ids)))
        ts = float(e.get("createdAt") or 0)
        if key not in groups:
            groups[key] = {
                "metricName": e["metricName"],
                "instrumentIds": ids,
                "timestamps": [],
            }
        groups[key]["timestamps"].append(ts)

    # Sort timestamps DESC within each group
    for g in groups.values():
        g["timestamps"].sort(reverse=True)

    # Sort groups: priority ASC, then latest timestamp DESC
    sorted_groups = sorted(
        groups.values(),
        key=lambda g: (
            _PRIORITY_MAP.get(g["metricName"], _FALLBACK_PRIORITY),
            -(g["timestamps"][0] if g["timestamps"] else 0),
        ),
    )

    return [
        TopEventItem(
            metricName=g["metricName"],
            instrumentIds=g["instrumentIds"],
            createdAt=g["timestamps"],
        )
        for g in sorted_groups[:top_k]
    ]


def _fetch_top_events(
    base_account_id: Optional[str],
    email: Optional[str],
    profile_id: Optional[str],
    top_k: int,
) -> List[TopEventItem]:
    db = _get_arango_db()
    cutoff_ts = time.time() - _THREE_MONTHS_SECONDS

    # Path 1: base_account_id → PG lookup → refProfileId in Arango
    if base_account_id:
        resolved_pid = _resolve_profile_id_from_account(base_account_id)
        if not resolved_pid:
            raise HTTPException(status_code=404, detail=f"No portfolio found for baseAccountId '{base_account_id}'.")
        cursor = db.aql.execute(
            _AQL_TOP_EVENTS_BY_PROFILE,
            bind_vars={"profile_id": resolved_pid, "priority_metrics": _PRIORITY_METRICS, "cutoff_ts": cutoff_ts},
        )
        return _sort_and_truncate(list(cursor), top_k)

    # Path 2: profile_id → refProfileId directly in Arango
    if profile_id:
        cursor = db.aql.execute(
            _AQL_TOP_EVENTS_BY_PROFILE,
            bind_vars={"profile_id": profile_id.strip(), "priority_metrics": _PRIORITY_METRICS, "cutoff_ts": cutoff_ts},
        )
        return _sort_and_truncate(list(cursor), top_k)

    # Path 3: email → fingerprintId via cdp_profile → events
    if email:
        fingerprints = _resolve_fingerprints_by_email(db, email)
        if not fingerprints:
            raise HTTPException(status_code=404, detail=f"No profile found for email '{email}'.")
        cursor = db.aql.execute(
            _AQL_TOP_EVENTS_BY_FINGERPRINT,
            bind_vars={"fingerprints": fingerprints, "priority_metrics": _PRIORITY_METRICS, "cutoff_ts": cutoff_ts},
        )
        return _sort_and_truncate(list(cursor), top_k)

    return []


# --- ENDPOINT ---

@router.get("/top", response_model=List[TopEventItem])
async def get_top_events(
    baseAccountId: Optional[str] = Query(None, description="User base account ID (resolved via PG portfolios)"),
    email: Optional[str] = Query(None, description="User email address"),
    profileId: Optional[str] = Query(None, description="User profile ID"),
    topK: int = Query(5, ge=5, le=50, description="Number of events to return (5-50)"),
):
    """
    Returns the top significant events for a user, sorted by event-type
    priority then recency.  Provide exactly one of `baseAccountId`, `email`, or `profileId`.
    """
    provided = sum(1 for v in [baseAccountId, email, profileId] if v)
    if provided == 0:
        raise HTTPException(
            status_code=400,
            detail="Exactly one of 'baseAccountId', 'email', or 'profileId' must be provided.",
        )
    if provided > 1:
        raise HTTPException(
            status_code=400,
            detail="Only one of 'baseAccountId', 'email', or 'profileId' may be provided at a time.",
        )

    try:
        # --- Cache read ---
        lookup = baseAccountId or profileId or email
        cache_key = f"leo:user_events:top:{lookup}:{topK}"
        cached = _cache_get(cache_key)
        if cached:
            logger.info(f"[Cache HIT] {cache_key}")
            return [TopEventItem(**item) for item in json.loads(cached)]

        # --- Cache miss ---
        logger.info(f"[Cache MISS] {cache_key}")
        results = _fetch_top_events(baseAccountId, email, profileId, topK)

        # --- Cache write ---
        _cache_set(cache_key, json.dumps([r.model_dump() for r in results]))

        return results
    except Exception as e:
        logger.error(f"Top Events error (baseAccountId={baseAccountId}, email={email}, profileId={profileId}): {e}")
        raise HTTPException(status_code=500, detail=str(e))


# ============================================================
# Metric Timestamps by Profile
# ============================================================

class MetricTimestampsItem(BaseModel):
    profileId: str
    timestamps: List[float] = Field(default_factory=list)


def _resolve_profile_ids_from_account(base_account_id: str) -> List[str]:
    """Resolve base_account_id → all profile_ids via PG portfolios table."""
    conn = _get_pg_connection()
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT DISTINCT profile_id FROM portfolios WHERE base_account_id = %s",
                (base_account_id.strip(),),
            )
            rows = cur.fetchall()
            return [
                (r["profile_id"] if isinstance(r, dict) else r[0])
                for r in rows
            ]
    finally:
        conn.close()


def _resolve_profile_ids_by_email(db, email: str) -> List[str]:
    """Resolve email → all profile _keys via ArangoDB cdp_profile."""
    aql = """
        FOR p IN cdp_profile
            FILTER p.primaryEmail == @email
            RETURN p._key
    """
    cursor = db.aql.execute(aql, bind_vars={"email": email.strip()})
    return [k for k in cursor if k]


_AQL_METRIC_TIMESTAMPS = """
FOR event IN cdp_trackingevent
    FILTER event.refProfileId IN @profile_ids
    FILTER event.metricName == @metric_name
    FILTER event.eventData.timestamp != null
    FILTER event.eventData.timestamp >= @cutoff_ts

    RETURN {
        profileId: event.refProfileId,
        ts: event.eventData.timestamp
    }
"""

_AQL_METRIC_TIMESTAMPS_WITH_INSTRUMENT = """
FOR event IN cdp_trackingevent
    FILTER event.refProfileId IN @profile_ids
    FILTER event.metricName == @metric_name
    FILTER event.eventData.timestamp != null
    FILTER event.eventData.timestamp >= @cutoff_ts

    // Check if event has any instrument field at all
    LET has_single = event.eventData.instrument_id != null AND event.eventData.instrument_id != ""
    LET has_list = IS_ARRAY(event.eventData.instrument_id_list) AND LENGTH(event.eventData.instrument_id_list) > 0
    LET has_instrument = has_single OR has_list

    // If event has no instrument fields → include it (pass-through)
    // If event has instrument fields → only include if target instrument matches
    FILTER !has_instrument
        OR (has_single AND event.eventData.instrument_id == @instrument_id)
        OR (has_list AND @instrument_id IN event.eventData.instrument_id_list)

    RETURN {
        profileId: event.refProfileId,
        ts: event.eventData.timestamp
    }
"""


def _fetch_metric_timestamps(
    profile_ids: List[str],
    metric_name: str,
    instrument_id: Optional[str] = None,
) -> List[MetricTimestampsItem]:
    db = _get_arango_db()
    cutoff_ts = time.time() - _THREE_MONTHS_SECONDS

    if instrument_id:
        query = _AQL_METRIC_TIMESTAMPS_WITH_INSTRUMENT
        bind_vars = {
            "profile_ids": profile_ids,
            "metric_name": metric_name,
            "cutoff_ts": cutoff_ts,
            "instrument_id": instrument_id.strip(),
        }
    else:
        query = _AQL_METRIC_TIMESTAMPS
        bind_vars = {
            "profile_ids": profile_ids,
            "metric_name": metric_name,
            "cutoff_ts": cutoff_ts,
        }

    cursor = db.aql.execute(query, bind_vars=bind_vars)

    # Group timestamps by profileId
    groups: dict[str, list[float]] = {}
    for row in cursor:
        pid = row["profileId"]
        ts = float(row.get("ts") or 0)
        groups.setdefault(pid, []).append(ts)

    # Sort timestamps DESC within each group
    return [
        MetricTimestampsItem(
            profileId=pid,
            timestamps=sorted(timestamps, reverse=True),
        )
        for pid, timestamps in groups.items()
    ]


@router.get("/metric-timestamps", response_model=List[MetricTimestampsItem])
async def get_metric_timestamps(
    baseAccountId: Optional[str] = Query(None, description="User base account ID"),
    email: Optional[str] = Query(None, description="User email address"),
    metricName: str = Query(..., description="Event metric name (e.g. 'order-created', 'ticker-view')"),
    instrumentId: Optional[str] = Query(None, description="Filter by instrument ID (optional)"),
):
    """
    Returns all timestamps (last 3 months) of a specific metricName,
    grouped by profileId.  Provide exactly one of `baseAccountId` or `email`.
    If instrumentId is given, only returns events matching that instrument
    (events without any instrument field are always included).
    """
    provided = sum(1 for v in [baseAccountId, email] if v)
    if provided == 0:
        raise HTTPException(status_code=400, detail="Exactly one of 'baseAccountId' or 'email' must be provided.")
    if provided > 1:
        raise HTTPException(status_code=400, detail="Only one of 'baseAccountId' or 'email' may be provided at a time.")

    try:
        lookup = baseAccountId or email
        cache_key = f"leo:user_events:metric_ts:{lookup}:{metricName}:{instrumentId or 'all'}"
        cached = _cache_get(cache_key)
        if cached:
            logger.info(f"[Cache HIT] {cache_key}")
            return [MetricTimestampsItem(**item) for item in json.loads(cached)]

        logger.info(f"[Cache MISS] {cache_key}")

        # Resolve to profile_ids
        if baseAccountId:
            profile_ids = _resolve_profile_ids_from_account(baseAccountId)
            if not profile_ids:
                raise HTTPException(status_code=404, detail=f"No portfolio found for baseAccountId '{baseAccountId}'.")
        else:
            db = _get_arango_db()
            profile_ids = _resolve_profile_ids_by_email(db, email)
            if not profile_ids:
                raise HTTPException(status_code=404, detail=f"No profile found for email '{email}'.")

        results = _fetch_metric_timestamps(profile_ids, metricName, instrumentId)
        _cache_set(cache_key, json.dumps([r.model_dump() for r in results]))
        return results

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Metric timestamps error (baseAccountId={baseAccountId}, email={email}, metricName={metricName}): {e}")
        raise HTTPException(status_code=500, detail=str(e))
