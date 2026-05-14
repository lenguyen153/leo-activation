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
_MS_THRESHOLD = 1e11  # timestamps > this are treated as milliseconds and divided by 1000


def _to_seconds(ts: float) -> float:
    """Normalize a unix timestamp to seconds; auto-converts ms inputs (> 1e11)."""
    return ts / 1000 if ts > _MS_THRESHOLD else ts


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
    """Uses the production DB — this module is read-only (event queries)."""
    settings = DatabaseSettings()
    return settings.get_pg_connection_api()


def _resolve_profile_ids_by_email(email: str) -> List[str]:
    """Resolve email → all profile_ids via PG cdp_profiles.primary_email."""
    conn = _get_pg_connection()
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT profile_id FROM cdp_profiles WHERE primary_email = %s",
                (email.strip(),),
            )
            rows = cur.fetchall()
            return [(r["profile_id"] if isinstance(r, dict) else r[0]) for r in rows]
    finally:
        conn.close()


def _resolve_profile_ids_by_base_account(base_account_id: str) -> List[str]:
    """Resolve base_account_id via cdp_profiles.ext_data → primary_email → all profile_ids."""
    conn = _get_pg_connection()
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT primary_email FROM cdp_profiles WHERE ext_data->>'base_account_id' = %s LIMIT 1",
                (base_account_id.strip(),),
            )
            row = cur.fetchone()
            if not row:
                return []
            email = row["primary_email"] if isinstance(row, dict) else row[0]
            if not email:
                return []
            cur.execute(
                "SELECT profile_id FROM cdp_profiles WHERE primary_email = %s",
                (email,),
            )
            rows = cur.fetchall()
            return [(r["profile_id"] if isinstance(r, dict) else r[0]) for r in rows]
    finally:
        conn.close()


_AQL_TOP_EVENTS_BY_PROFILES = """
FOR event IN cdp_trackingevent
    FILTER event.refProfileId IN @profile_ids
    FILTER event.eventData.timestamp != null
    FILTER event.eventData.timestamp >= @cutoff_ts
    FILTER @upper_ts == null OR event.eventData.timestamp <= @upper_ts
    FILTER @metric_name == null OR event.metricName == @metric_name

    LET single = event.eventData.instrument_id
    LET list   = event.eventData.instrument_id_list
    LET ids = (
        single != null AND single != ""
        ? [single]
        : (IS_ARRAY(list) AND LENGTH(list) > 0 ? list : [])
    )

    FILTER LENGTH(ids) > 0
    FILTER event.metricName IN @priority_metrics OR LENGTH(ids) > 0
    FILTER @instrument_id == null OR @instrument_id IN ids

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
    from_ts: Optional[float] = None,
    to_ts: Optional[float] = None,
    instrument_id: Optional[str] = None,
    metric_name: Optional[str] = None,
) -> List[TopEventItem]:
    if base_account_id:
        profile_ids = _resolve_profile_ids_by_base_account(base_account_id)
        if not profile_ids:
            raise HTTPException(status_code=404, detail=f"No profile found for baseAccountId '{base_account_id}'.")
    elif profile_id:
        profile_ids = [profile_id.strip()]
    elif email:
        profile_ids = _resolve_profile_ids_by_email(email)
        if not profile_ids:
            raise HTTPException(status_code=404, detail=f"No profile found for email '{email}'.")
    else:
        return []

    db = _get_arango_db()
    # Stored timestamps are in milliseconds; convert seconds-based inputs to ms
    cutoff_ts = (from_ts * 1000) if from_ts is not None else (time.time() - _THREE_MONTHS_SECONDS) * 1000
    upper_ts = (to_ts * 1000) if to_ts is not None else None
    cursor = db.aql.execute(
        _AQL_TOP_EVENTS_BY_PROFILES,
        bind_vars={
            "profile_ids": profile_ids,
            "priority_metrics": _PRIORITY_METRICS,
            "cutoff_ts": cutoff_ts,
            "upper_ts": upper_ts,
            "metric_name": metric_name,
            "instrument_id": instrument_id,
        },
    )
    return _sort_and_truncate(list(cursor), top_k)


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
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Top Events error (baseAccountId={baseAccountId}, email={email}, profileId={profileId}): {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/top-range", response_model=List[TopEventItem])
async def get_top_events_range(
    baseAccountId: Optional[str] = Query(None, description="User base account ID (resolved via PG portfolios)"),
    email: Optional[str] = Query(None, description="User email address"),
    profileId: Optional[str] = Query(None, description="User profile ID"),
    topK: int = Query(5, ge=5, le=50, description="Number of events to return (5-50)"),
    fromTs: float = Query(..., description="Start of time range (unix timestamp)"),
    toTs: Optional[float] = Query(None, description="End of time range (unix timestamp, defaults to now)"),
    instrumentId: Optional[str] = Query(None, description="Filter by instrument ID (optional)"),
    metricName: Optional[str] = Query(None, description="Filter by metric name (optional)"),
):
    """
    Same as /top but filtered to events within [fromTs, toTs].
    Provide exactly one of `baseAccountId`, `email`, or `profileId`.
    `fromTs` cannot be more than 3 months old. `toTs` defaults to current time if omitted.
    Optionally filter by `instrumentId` and/or `metricName`; omit either to return all.
    """
    fromTs = _to_seconds(fromTs)
    toTs = _to_seconds(toTs) if toTs is not None else time.time()

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
    if fromTs < time.time() - _THREE_MONTHS_SECONDS:
        raise HTTPException(status_code=400, detail="'fromTs' cannot be more than 3 months in the past.")
    if fromTs >= toTs:
        raise HTTPException(status_code=400, detail="'fromTs' must be less than 'toTs'.")

    try:
        lookup = baseAccountId or profileId or email
        cache_key = f"leo:user_events:top_range:{lookup}:{topK}:{fromTs}:{toTs}:{instrumentId or 'all'}:{metricName or 'all'}"
        cached = _cache_get(cache_key)
        if cached:
            logger.info(f"[Cache HIT] {cache_key}")
            return [TopEventItem(**item) for item in json.loads(cached)]

        logger.info(f"[Cache MISS] {cache_key}")
        results = _fetch_top_events(
            baseAccountId, email, profileId, topK,
            from_ts=fromTs, to_ts=toTs,
            instrument_id=instrumentId, metric_name=metricName,
        )

        _cache_set(cache_key, json.dumps([r.model_dump() for r in results]))
        return results
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Top Events Range error (baseAccountId={baseAccountId}, email={email}, profileId={profileId}): {e}")
        raise HTTPException(status_code=500, detail=str(e))


# ============================================================
# Metric Timestamps by Profile
# ============================================================

class MetricTimestampsItem(BaseModel):
    profileId: str
    timestamps: List[float] = Field(default_factory=list)



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

        # Resolve to profile_ids via PG cdp_profiles
        if baseAccountId:
            profile_ids = _resolve_profile_ids_by_base_account(baseAccountId)
            if not profile_ids:
                raise HTTPException(status_code=404, detail=f"No profile found for baseAccountId '{baseAccountId}'.")
        else:
            profile_ids = _resolve_profile_ids_by_email(email)
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