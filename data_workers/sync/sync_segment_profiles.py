import logging
import uuid
import asyncio
from concurrent.futures import ThreadPoolExecutor
from typing import Optional
from functools import partial

import redis as redis_lib

# --- Imports (Assuming these exist in your project structure) ---
from data_models.dbo_tenant import resolve_tenant_id, set_tenant_context
from data_utils.db_factory import get_db_context
from data_utils.settings import DatabaseSettings
from data_workers.repositories.arango_profile_repository import ArangoProfileRepository
from data_workers.sync.arango_to_pg_profile_sync_service import ArangoToPostgresSyncService
from data_workers.repositories.pg_profile_repository import PGProfileRepository

logger = logging.getLogger(__name__)

# Global executor for offloading sync tasks to threads
# You can also pass a specific executor if running inside a larger app
_DEFAULT_EXECUTOR = ThreadPoolExecutor(max_workers=4)


def _populate_fingerprint_cache(arango_db, segment_id: Optional[str], segment_name: Optional[str]) -> None:
    """
    After profile sync, cache fingerprintId→profile_id in Redis DB 2.
    The real-time scoring consumer uses this for O(1) lookups instead of
    querying ArangoDB per event.
    """
    import os
    cache_redis_url = os.getenv("CDC_REDIS_URL", "redis://redis:6379/2")
    try:
        r = redis_lib.from_url(cache_redis_url, decode_responses=True)

        # Build the appropriate AQL filter depending on what's available
        if segment_id:
            query = """
            FOR p IN cdp_profile
                FILTER @seg IN p.inSegments[*].id
                FILTER p.fingerprintId != null
                RETURN { fid: p.fingerprintId, pid: p._key }
            """
            bind_vars = {"seg": segment_id}
        elif segment_name:
            query = """
            FOR p IN cdp_profile
                FILTER @seg IN p.inSegments[*].name
                FILTER p.fingerprintId != null
                RETURN { fid: p.fingerprintId, pid: p._key }
            """
            bind_vars = {"seg": segment_name}
        else:
            logger.warning("No segment filter for fingerprint cache, skipping")
            return

        cursor = arango_db.aql.execute(query, bind_vars=bind_vars)
        count = 0
        for doc in cursor:
            fid, pid = doc["fid"], doc["pid"]
            if fid and pid:
                r.setex(f"fp:{fid}", 86400, pid)
                count += 1
        logger.info("Fingerprint cache populated: %d entries (TTL=24h)", count)
    except Exception:
        logger.exception("Failed to populate fingerprint cache (non-fatal)")


def _execute_sync_logic(
    segment_name: Optional[str],
    tenant_id: Optional[str], 
    segment_id: Optional[str],                        
    last_sync_ts: Optional[str]
) -> int:
    """
    Core synchronous logic. This function contains the blocking DB operations.
    It is private (_) because external callers should use the public wrappers.
    """
    logger.info(
        "Starting sync (Core Logic) | Segment: %s | Tenant: %s | SegmentID: %s", 
        segment_name, tenant_id, segment_id
    )

    db_settings = DatabaseSettings()
    synced_count = 0

    # 1. Use the DB Context manager
    with get_db_context(db_settings) as pg_session:
        try:
            # 2. ArangoDB Setup (Assuming standard blocking driver)
            arango_db = db_settings.get_arango_db()
            
            # 3. Handle Tenant Context
            if tenant_id is None:
                # Default to "master" if not provided
                resolved_tid = resolve_tenant_id(pg_session, "master")
            else:
                resolved_tid = uuid.UUID(str(tenant_id))

            # CRITICAL: Set RLS context
            set_tenant_context(pg_session, resolved_tid)

            # 4. Infrastructure Wiring
            arango_repo = ArangoProfileRepository(arango_db, batch_size=500)
            pg_repo = PGProfileRepository(pg_session)

            sync_service = ArangoToPostgresSyncService(
                arango_repo=arango_repo,
                pg_repo=pg_repo,
                tenant_id=resolved_tid,
            )

            # 5. Execute Sync
            synced_count = sync_service.sync_segment(
                tenant_id=resolved_tid, 
                segment_id=segment_id, 
                segment_name=segment_name, 
                last_sync_ts=last_sync_ts
            )

            # 6. Commit
            pg_session.commit()

            logger.info(
                "Sync completed successfully. Tenant: %s | Profiles: %d",
                resolved_tid, synced_count
            )

            # 7. Populate fingerprint→profile_id Redis cache for real-time CDC pipeline
            # Use a fresh ArangoDB connection to avoid stale/closed session issues
            # try:
            #     fresh_arango = db_settings.get_arango_db()
            #     _populate_fingerprint_cache(fresh_arango, segment_id, segment_name)
            # except Exception:
            #     logger.exception("Failed to create ArangoDB connection for fingerprint cache (non-fatal)")

        except Exception as e:
            pg_session.rollback()
            logger.error("Sync failed: %s", str(e), exc_info=True)
            raise e

    return synced_count


# ==============================================================================
# 1. Synchronous Entry Point (Blocking)
# ==============================================================================
def run_synch_profiles(
    segment_name: Optional[str] = None,
    tenant_id: Optional[str] = None, 
    segment_id: Optional[str] = None,                        
    last_sync_ts: Optional[str] = None
) -> int:
    """
    Standard blocking call. Use this for CLI scripts, Celery workers, or scripts.
    """
    return _execute_sync_logic(segment_name, tenant_id, segment_id, last_sync_ts)


# ==============================================================================
# 2. Asynchronous Entry Point (Non-Blocking)
# ==============================================================================
async def run_synch_profiles_async(
    segment_name: Optional[str] = None,
    tenant_id: Optional[str] = None, 
    segment_id: Optional[str] = None,                        
    last_sync_ts: Optional[str] = None,
    executor: Optional[ThreadPoolExecutor] = None
) -> int:
    """
    Async wrapper. Use this in FastAPI routes or asyncio loops.
    It offloads the blocking _execute_sync_logic to a thread pool.
    """
    loop = asyncio.get_running_loop()
    
    # Use the passed executor or fallback to the module-level default
    actual_executor = executor or _DEFAULT_EXECUTOR

    # Create a partial function to pass arguments cleanly
    func = partial(
        _execute_sync_logic,
        segment_name=segment_name,
        tenant_id=tenant_id,
        segment_id=segment_id,
        last_sync_ts=last_sync_ts
    )

    # Run in thread pool to avoid blocking the async event loop
    logger.info("Offloading sync task to thread pool...")
    result = await loop.run_in_executor(actual_executor, func)
    
    return result