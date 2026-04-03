"""Throttle layer — prevent duplicate NBA dispatches within 24h per (profile, ticker)."""

import redis

THROTTLE_TTL_S = 86400  # 24 hours

_redis: redis.Redis | None = None


def _get_redis(redis_url: str) -> redis.Redis:
    global _redis
    if _redis is None:
        _redis = redis.from_url(redis_url, decode_responses=True)
    return _redis


def _key(profile_id: str, ticker: str) -> str:
    return f"nba_throttle:{profile_id}:{ticker}"


def is_throttled(redis_url: str, profile_id: str, ticker: str) -> bool:
    """Return True if this (profile, ticker) pair was already dispatched within 24h."""
    r = _get_redis(redis_url)
    return r.exists(_key(profile_id, ticker)) > 0


def set_throttle(redis_url: str, profile_id: str, ticker: str) -> None:
    """Mark this (profile, ticker) as dispatched for 24h."""
    r = _get_redis(redis_url)
    r.setex(_key(profile_id, ticker), THROTTLE_TTL_S, "1")
