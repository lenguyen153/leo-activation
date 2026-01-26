import logging
from typing import Optional
import uuid

from data_models.dbo_tenant import resolve_tenant_id, set_tenant_context, get_default_tenant_id

from data_utils.db_factory import get_db_context 
from data_utils.settings import DatabaseSettings
from data_workers.arango_profile_repository import ArangoProfileRepository
from data_workers.arango_to_pg_profile_sync_service import ArangoToPostgresSyncService
from data_workers.pg_profile_repository import PGProfileRepository

logger = logging.getLogger(__name__)

def run_synch_profiles(
    segment_name: Optional[str] = None,
    tenant_id: Optional[str] = None, 
    segment_id: Optional[str] = None,                        
    last_sync_ts: Optional[str] = None
) -> int:
    """
    Entry point for syncing profiles of a given segment from ArangoDB into PostgreSQL.
    """

    logger.info(
        "Starting sync | Segment: %s | Tenant: %s | SegmentID: %s | LastSync: %s", 
        segment_name, tenant_id, segment_id, last_sync_ts
    )

    db_settings = DatabaseSettings()
    synced_count = 0

    # 1. Use the DB Context manager to ensure the connection is closed automatically
    with get_db_context(db_settings) as pg_session:
        try:
            # 2. ArangoDB Setup
            arango_db = db_settings.get_arango_db()
            
            # 3. Handle Tenant Context
            # If tenant_id isn't provided, we default to "master"
            if tenant_id is None:
                resolved_tid = resolve_tenant_id(pg_session, "master")
            else:
                # Ensure it's a UUID object if it came in as a string
                resolved_tid = uuid.UUID(str(tenant_id))

            # CRITICAL: Set the RLS context for the current transaction
            set_tenant_context(pg_session, resolved_tid)

            # 4. Infrastructure Wiring
            arango_repo = ArangoProfileRepository(arango_db, batch_size=2)
            
            # Assuming PGProfileRepository can accept a session or its underlying connection
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

            # 6. Commit the changes
            pg_session.commit()

            logger.info(
                "Sync completed. Tenant: %s | Segment: %s | Profiles: %d",
                resolved_tid, segment_name, synced_count
            )

        except Exception as e:
            pg_session.rollback()
            logger.error("Sync failed for segment %s: %s", segment_name, str(e), exc_info=True)
            raise 

    return synced_count