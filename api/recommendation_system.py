import json
import logging
import os
from unittest import result
import psycopg
import redis
from typing import List, Dict, Any, Optional, Union
from fastapi import APIRouter, HTTPException, Path, Query, Depends, Request
from fastapi.responses import PlainTextResponse
from pydantic import BaseModel, Field




# --- IMPORTS ---
from data_utils.settings import DatabaseSettings
from main_configs import REDIS_URL, RECOMMENDATION_CACHE_TTL

from agentic_tools.channels.zalo import ZaloOAChannel
# from agentic_tools.channels.zalo import send_simple_text

# Import Workers (The Logic Layer)
# We handle import errors gracefully to prevent crashing if workers aren't ready
try:
    from agentic_tools.recommendation_system.interest_score import (
        resolve_ids, 
        get_interested_users, 
        get_profile_affinity
    )
    from agentic_tools.recommendation_orchestrator import get_next_best_action
    from agentic_tools.recommendation_orchestrator import get_next_likely_action
except ImportError as e:
    import logging
    logging.warning(f"⚠️ Worker modules missing: {e}. Recommendation endpoints will fail.")

# --- LOGGING ---
logger = logging.getLogger("LEO Recommendation API")

# --- REDIS CACHE (module-level singleton, graceful fallback) ---
_redis_client: Optional[redis.Redis] = None
try:
    if REDIS_URL:
        _redis_client = redis.from_url(REDIS_URL, decode_responses=True)
        _redis_client.ping()
        logger.info("Redis cache connected for recommendation endpoints.")
    else:
        logger.warning("REDIS_URL not set. Recommendation caching disabled.")
except Exception as e:
    logger.warning(f"Redis unavailable — recommendation caching disabled. {e}")
    _redis_client = None

def get_arango_db():
    settings = DatabaseSettings()
    return settings.get_arango_db()


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
    prefix="/recommendation",
    tags=["Recommendation System"]
)

# --- DEPENDENCIES ---
def get_db():
    settings = DatabaseSettings()
    conn = settings.get_pg_connection()
    try:
        yield conn
    finally:
        conn.close()

# --- DATA MODELS (Response Schemas) ---

class InterestedUserResponse(BaseModel):
    profile_id: str
    score: float
    raw_points: float

class UserProfileInterestResponse(BaseModel):
    """Schema for the 360-view profile endpoint"""
    profile_id: Optional[str] = None
    identities: List[str] = Field(default_factory=list)
    primary_email: Optional[str] = None
    raw_scores: Dict[str, float]
    interest_scores: Dict[str, float]
    next_likely_actions: Dict[str, str]
    segments: List[str]

class ActionDetail(BaseModel):
    """Details for a specific stock's recommended action"""
    action: str
    channel: str
    confidence_score: float
    reason: str
    
class NextBestActionResponse(BaseModel):
    """Standardized response for the NBA decision engine."""
    profile_id: str
    next_best_actions: Dict[str, ActionDetail]

class LikelyActionDetail(BaseModel):
    """Details for a specific stock's recommended action"""
    action: str
    confidence_score: float

class NextLikelyActionResponse(BaseModel):
    """Predictive: What the USER will likely do."""
    profile_id: str
    next_likely_actions: Dict[str, LikelyActionDetail]


class SegmentProfileResponse(BaseModel):
    """Profile ID and email for a user in a segment."""
    profile_id: str
    primary_email: Optional[str] = None


# ============================================================
# API ENDPOINTS
# ============================================================

_SEGMENT_PROD = "Production 1invest Users"
_SEGMENT_UAT = "UAT 1invest Users"


async def _interested_by_segment(
    ticker: str,
    min_score: float,
    conn: psycopg.Connection,
    segment_name: Optional[str] = None,
) -> List[InterestedUserResponse]:
    target_tenant = os.getenv("TARGET_TENANT", "master")
    tenant_uuid, _ = resolve_ids(conn, target_tenant, "Active in last 3 months")
    raw_results = get_interested_users(conn, tenant_uuid, ticker, min_score)

    if segment_name:
        allowed_ids = {p.profile_id for p in _get_profiles_for_segment(segment_name, conn)}
        raw_results = [r for r in raw_results if r["profile_id"] in allowed_ids]

    return [InterestedUserResponse(**r) for r in raw_results]


# 1a. FIND AUDIENCE — All segments
@router.get("/interested/{ticker}", response_model=List[InterestedUserResponse])
async def get_interested_users_endpoint(
    ticker: str,
    min_score: float = Query(0.5, description="Minimum score 0.0-1.0"),
    conn: psycopg.Connection = Depends(get_db)
):
    """Finds all users interested in a ticker regardless of segment."""
    try:
        cache_key = f"leo:rec:interested:all:{ticker}:{min_score}"
        cached = _cache_get(cache_key)
        if cached:
            logger.info(f"[Cache HIT] {cache_key}")
            return [InterestedUserResponse(**r) for r in json.loads(cached)]

        logger.info(f"[Cache MISS] {cache_key}")
        results = await _interested_by_segment(ticker, min_score, conn)
        _cache_set(cache_key, json.dumps([r.model_dump() for r in results]))
        return results
    except Exception as e:
        logger.error(f"❌ Audience Query Error for '{ticker}': {e}")
        raise HTTPException(status_code=500, detail=str(e))


# 1b. FIND AUDIENCE — Production segment only
@router.get("/interested-prod/{ticker}", response_model=List[InterestedUserResponse])
async def get_interested_users_prod_endpoint(
    ticker: str,
    min_score: float = Query(0.5, description="Minimum score 0.0-1.0"),
    conn: psycopg.Connection = Depends(get_db)
):
    """Finds users interested in a ticker, filtered to Production 1invest Users."""
    try:
        cache_key = f"leo:rec:interested:prod:{ticker}:{min_score}"
        cached = _cache_get(cache_key)
        if cached:
            logger.info(f"[Cache HIT] {cache_key}")
            return [InterestedUserResponse(**r) for r in json.loads(cached)]

        logger.info(f"[Cache MISS] {cache_key}")
        results = await _interested_by_segment(ticker, min_score, conn, _SEGMENT_PROD)
        _cache_set(cache_key, json.dumps([r.model_dump() for r in results]))
        return results
    except Exception as e:
        logger.error(f"❌ Audience Query Error (prod) for '{ticker}': {e}")
        raise HTTPException(status_code=500, detail=str(e))


# 1c. FIND AUDIENCE — UAT segment only
@router.get("/interested-uat/{ticker}", response_model=List[InterestedUserResponse])
async def get_interested_users_uat_endpoint(
    ticker: str,
    min_score: float = Query(0.5, description="Minimum score 0.0-1.0"),
    conn: psycopg.Connection = Depends(get_db)
):
    """Finds users interested in a ticker, filtered to UAT 1invest Users."""
    try:
        cache_key = f"leo:rec:interested:uat:{ticker}:{min_score}"
        cached = _cache_get(cache_key)
        if cached:
            logger.info(f"[Cache HIT] {cache_key}")
            return [InterestedUserResponse(**r) for r in json.loads(cached)]

        logger.info(f"[Cache MISS] {cache_key}")
        results = await _interested_by_segment(ticker, min_score, conn, _SEGMENT_UAT)
        _cache_set(cache_key, json.dumps([r.model_dump() for r in results]))
        return results
    except Exception as e:
        logger.error(f"❌ Audience Query Error (uat) for '{ticker}': {e}")
        raise HTTPException(status_code=500, detail=str(e))


# 2. PROFILE 360 (What does this user like?)
@router.get("/profile_affinity/{lookup_key}", response_model=UserProfileInterestResponse)
async def get_profile_affinity_endpoint(
    lookup_key: str = Path(..., description="Profile ID, Email, or Identity"),
    conn: psycopg.Connection = Depends(get_db)
):
    """
    Gets a 360-view of a user: Identity + Calculated Interest Scores.
    Useful for: Customer Support Dashboard or User Profile Page.
    """
    try:
        target_tenant = os.getenv("TARGET_TENANT", "master")

        # --- Cache read ---
        cache_key = f"leo:rec:affinity:{target_tenant}:{lookup_key}"
        cached = _cache_get(cache_key)
        if cached:
            logger.info(f"[Cache HIT] {cache_key}")
            return UserProfileInterestResponse.model_validate_json(cached)

        logger.info(f"[Cache MISS] {cache_key}")
        tenant_uuid, _ = resolve_ids(conn, target_tenant, "Active in last 3 months")
        data = get_profile_affinity(conn, tenant_uuid, lookup_key)

        if not data:
            return UserProfileInterestResponse(
                profile_id=None,
                identities=[],
                raw_scores={},
                interest_scores={},
                next_likely_actions={},
                segments=[]
            )

        response = UserProfileInterestResponse(**data)
        _cache_set(cache_key, response.model_dump_json())
        return response

    except Exception as e:
        logger.error(f"❌ Profile Lookup Error for '{lookup_key}': {e}")
        raise HTTPException(status_code=500, detail=str(e))


# 3. NEXT BEST ACTION (What should we do with them?)
@router.get("/nba/{user_id}", response_model=NextBestActionResponse)
async def get_nba_endpoint(
    user_id: str = Path(..., description="The target User Profile ID"),
    conn: psycopg.Connection = Depends(get_db)
):
    """
    Calculates the single best action to take for a user based on
    their highest interest score and segment persona.
    Useful for: Marketing Triggers (e.g., "Show this Banner").
    """
    try:
        target_tenant = os.getenv("TARGET_TENANT", "master")

        # --- Cache read ---
        cache_key = f"leo:rec:nba:{target_tenant}:{user_id}"
        cached = _cache_get(cache_key)
        if cached:
            logger.info(f"[Cache HIT] {cache_key}")
            return NextBestActionResponse.model_validate_json(cached)

        logger.info(f"[Cache MISS] {cache_key}")
        tenant_uuid, _ = resolve_ids(conn, target_tenant, "Active in last 3 months")
        result = get_next_best_action(conn, tenant_uuid, user_id)

        response = NextBestActionResponse(
            profile_id=result["profile_id"],
            next_best_actions=result["next_best_actions"]
        )
        _cache_set(cache_key, response.model_dump_json())
        return response

    except Exception as e:
        logger.error(f"❌ NBA Error for '{user_id}': {e}")
        raise HTTPException(status_code=500, detail=str(e))

# 4. NEXT LIKELY ACTION (Predictive - What THEY do)
@router.get("/nla/{user_id}", response_model=NextLikelyActionResponse)
async def get_nla_endpoint(
    user_id: str = Path(..., description="The target User Profile ID"),
    conn: psycopg.Connection = Depends(get_db)
):
    """
    Returns the forecasted next user event and its probability.
    """
    try:
        target_tenant = os.getenv("TARGET_TENANT", "master")

        cache_key = f"leo:rec:nla:{target_tenant}:{user_id}"
        cached = _cache_get(cache_key)
        if cached:
            logger.info(f"[Cache HIT] {cache_key}")
            return NextLikelyActionResponse.model_validate_json(cached)

        logger.info(f"[Cache MISS] {cache_key}")
        tenant_uuid, _ = resolve_ids(conn, target_tenant, "Active in last 3 months")
        result = get_next_likely_action(conn, tenant_uuid, user_id)

        response = NextLikelyActionResponse(
            profile_id=result["profile_id"],
            next_likely_actions=result["next_likely_actions"]
        )
        _cache_set(cache_key, response.model_dump_json())
        return response

    except Exception as e:
        logger.error(f"❌ NLA Error for '{user_id}': {e}")
        raise HTTPException(status_code=500, detail=str(e))



_SQL_PROFILES_IN_SEGMENT = """
    SELECT profile_id, primary_email
    FROM cdp_profiles
    WHERE segments @> jsonb_build_array(jsonb_build_object('name', %s::text))
"""


def _get_profiles_for_segment(segment_name: str, conn: psycopg.Connection) -> List[SegmentProfileResponse]:
    with conn.cursor(row_factory=psycopg.rows.dict_row) as cur:
        cur.execute(_SQL_PROFILES_IN_SEGMENT, (segment_name,))
        return [SegmentProfileResponse(**row) for row in cur.fetchall()]


# FIX 1: The path should just be "/webhook/zalo"
@router.post("/webhook/zalo")
async def handle_zalo_webhook(request: Request):
    """
    Listens for events from the Zalo Official Account.
    """
    try:
        payload = await request.json()
        event_name = payload.get("event_name")
        logger.info(f"[Zalo Webhook] Received event: {event_name}")

        if event_name != "user_send_text":
            return {"error": 0, "message": "Success"}

        if event_name == "user_send_text":
            sender_id = payload.get("sender", {}).get("id")
            message_text = payload.get("message", {}).get("text", "")
            
            # The Webhook catches the secret code!
            if message_text == "#GET_WEBSITE_LINK":
                print(f"🎉 BOOM! User {sender_id} just reset their 7-day timer!")
                
                # FIX 2: Make sure your channel has the DB client so it can refresh tokens!
                db = get_arango_db() 
                channel = ZaloOAChannel(db_client=db)
                
                # The Webhook delivers the actual URL
                reply_text = (
                    "Cảm ơn bạn đã quan tâm! 🎁\n\n"
                    "👉 Truy cập ngay website để nhận đặc quyền của bạn:\n"
                    "https://trading-uat.1invest.vn/priceboard"
                )
                
                channel.send_simple_text(sender_id, reply_text)
                
        return {"error": 0, "message": "Success"}

    except Exception as e:
        print(f"Webhook Error: {e}")
        return {"error": -1, "message": "Internal Server Error"}