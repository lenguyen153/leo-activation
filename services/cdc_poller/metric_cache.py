"""In-memory cache of cdp_eventmetric scores, refreshed periodically."""

import logging
import threading
import time
from typing import Dict

from arango import ArangoClient

from services.cdc_poller.config import ARANGO_HOST, ARANGO_DB, ARANGO_USER, ARANGO_PASSWORD

logger = logging.getLogger(__name__)

_cache: Dict[str, float] = {}
_lock = threading.Lock()
_REFRESH_INTERVAL_S = 300  # 5 minutes


def _fetch_metrics() -> Dict[str, float]:
    """Run AQL to load all event metric scores."""
    client = ArangoClient(hosts=ARANGO_HOST)
    db = client.db(ARANGO_DB, username=ARANGO_USER, password=ARANGO_PASSWORD)
    query = "FOR m IN cdp_eventmetric RETURN {name: m.eventName, score: m.score}"
    cursor = db.aql.execute(query)
    result = {doc["name"]: float(doc["score"]) for doc in cursor}
    logger.info("Refreshed metric cache: %d metrics loaded", len(result))
    return result


def get_metric_score(metric_name: str) -> float:
    """Lookup metric score from cache. Returns 0.0 if unknown."""
    with _lock:
        return _cache.get(metric_name, 0.0)


def refresh_cache() -> None:
    """Force a cache refresh."""
    global _cache
    try:
        new_data = _fetch_metrics()
        with _lock:
            _cache.clear()
            _cache.update(new_data)
    except Exception:
        logger.exception("Failed to refresh metric cache")


def start_background_refresh() -> threading.Thread:
    """Start a daemon thread that refreshes the metric cache every 5 minutes."""

    def _loop():
        while True:
            refresh_cache()
            time.sleep(_REFRESH_INTERVAL_S)

    t = threading.Thread(target=_loop, daemon=True, name="metric-cache-refresh")
    t.start()
    logger.info("Started metric cache refresh thread (interval=%ds)", _REFRESH_INTERVAL_S)
    return t
