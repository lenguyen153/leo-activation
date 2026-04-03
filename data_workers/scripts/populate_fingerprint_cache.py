"""
Populate fingerprint→profile_id cache in Redis DB 2.
Used by the real-time scoring consumer for O(1) profile lookups.
Keys have 24h TTL. Intended to run every 5 minutes via cron.
"""

import logging
import os

import redis

from data_utils.settings import DatabaseSettings

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def main():
    cdc_redis_url = os.getenv("CDC_REDIS_URL", "redis://redis:6379/2")
    target_segment = os.getenv("TARGET_SEGMENT", "Active last 3 months")

    settings = DatabaseSettings()
    db = settings.get_arango_db()
    r = redis.from_url(cdc_redis_url, decode_responses=True)

    query = """
    FOR p IN cdp_profile
        FILTER @seg IN p.inSegments[*].name
        FILTER p.fingerprintId != null
        RETURN { fid: p.fingerprintId, pid: p._key }
    """
    cursor = db.aql.execute(query, bind_vars={"seg": target_segment})
    count = 0
    for doc in cursor:
        if doc["fid"] and doc["pid"]:
            r.setex(f"fp:{doc['fid']}", 86400, doc["pid"])
            count += 1

    logger.info(
        "[FP Cache] Populated %d fingerprint entries (TTL=24h, segment=%s)",
        count,
        target_segment,
    )


if __name__ == "__main__":
    main()
