"""
Populate fingerprint→profile_id cache in Redis DB 2.
Used by the real-time scoring consumer for O(1) profile lookups.
Keys have 24h TTL. Intended to run every 5 minutes via cron.
"""

import os

import redis

from data_utils.logging_config import configure_logging, get_logger, log_event
from data_utils.settings import DatabaseSettings

configure_logging()
logger = get_logger(__name__)


def main():
    cdc_redis_url = os.getenv("CDC_REDIS_URL", "redis://redis:6379/2")
    target_segment = os.getenv("TARGET_SEGMENT", "Active in last 3 months")

    settings = DatabaseSettings()
    db = settings.get_arango_db()
    r = redis.from_url(cdc_redis_url, decode_responses=True)

    # Step 1: fingerprintId → cdp_profile._key for segment members
    profile_q = """
    FOR p IN cdp_profile
        FILTER @seg IN p.inSegments[*].name
        FILTER p.fingerprintId != null AND p.fingerprintId != ""
        RETURN { fid: p.fingerprintId, pid: p._key }
    """
    fp_map = {doc["fid"]: doc["pid"] for doc in db.aql.execute(profile_q, bind_vars={"seg": target_segment})}
    if not fp_map:
        log_event(logger, "fingerprint_cache_populated", entries=0, segment=target_segment)
        return

    # Step 2: resolve fingerprintId → refProfileId from latest events (batch)
    resolve_q = """
    FOR e IN cdp_trackingevent
        FILTER e.fingerprintId IN @fids
        FILTER e.refProfileId != null AND e.refProfileId != ""
        COLLECT fid = e.fingerprintId INTO grp
        LET latest = FIRST(
            FOR g IN grp
                SORT g.e.createdAt DESC
                LIMIT 1
                RETURN g.e.refProfileId
        )
        RETURN { fid: fid, ref: latest }
    """
    ref_map = {
        doc["fid"]: doc["ref"]
        for doc in db.aql.execute(resolve_q, bind_vars={"fids": list(fp_map.keys())})
        if doc.get("ref")
    }

    # Step 3: merge — prefer refProfileId, fall back to cdp_profile._key
    count = 0
    for fid, pid in fp_map.items():
        resolved = ref_map.get(fid, pid)
        r.setex(f"fp:{fid}", 86400, resolved)
        count += 1

    log_event(logger, "fingerprint_cache_populated", entries=count, segment=target_segment)


if __name__ == "__main__":
    main()
