"""Redis-backed WAL tick checkpoint for CDC poller."""

import logging

import redis
import requests

from services.cdc_poller.config import ARANGO_USER, ARANGO_PASSWORD, REDIS_URL, get_arango_replication_base_url

logger = logging.getLogger(__name__)

TICK_KEY = "cdc:arango:last_tick"

_redis: redis.Redis | None = None


def _get_redis() -> redis.Redis:
    global _redis
    if _redis is None:
        _redis = redis.from_url(REDIS_URL, decode_responses=True)
    return _redis


def get_tick() -> int:
    """Return the last successfully processed WAL tick, or 0."""
    r = _get_redis()
    val = r.get(TICK_KEY)
    if val is not None:
        return int(val)
    return 0


def set_tick(tick: int) -> None:
    """Persist the latest processed WAL tick."""
    r = _get_redis()
    r.set(TICK_KEY, str(tick))


def bootstrap_tick() -> int:
    """Fetch current WAL state from ArangoDB and seed Redis if empty."""
    r = _get_redis()
    existing = r.get(TICK_KEY)
    if existing is not None:
        return int(existing)

    # Query ArangoDB replication logger state to get latest tick
    base = get_arango_replication_base_url()
    url = f"{base}/_api/replication/logger-state"
    resp = requests.get(url, auth=(ARANGO_USER, ARANGO_PASSWORD), timeout=10)
    resp.raise_for_status()
    data = resp.json()
    logger.info("ArangoDB logger-state response keys: %s", list(data.keys()))

    # Handle different ArangoDB version response formats
    if "state" in data and "lastLogTick" in data["state"]:
        last_tick = int(data["state"]["lastLogTick"])
    elif "lastLogTick" in data:
        last_tick = int(data["lastLogTick"])
    elif "tick" in data:
        last_tick = int(data["tick"])
    else:
        logger.warning("Unknown logger-state format: %s. Starting from tick 0.", data)
        last_tick = 0

    set_tick(last_tick)
    logger.info("Bootstrapped WAL tick from logger-state: %d", last_tick)
    return last_tick
