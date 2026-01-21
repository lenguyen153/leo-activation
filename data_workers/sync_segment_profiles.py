import logging
import sys
from typing import Optional



from data_models.pg_tenant import resolve_and_set_default_tenant
from data_utils.arango_client import get_arango_db
from data_utils.pg_client import get_pg_connection
from data_utils.settings import DatabaseSettings
from data_workers.arango_profile_repository import ArangoProfileRepository
from data_workers.arango_to_pg_profile_sync_service import ArangoToPostgresSyncService
from data_workers.pg_profile_repository import PGProfileRepository


logger = logging.getLogger(__name__)


def run_synch_profiles(segment_name: Optional[str] = None,
                       tenant_id: Optional[str] = None, 
                        segment_id: Optional[str] = None,                        
                        last_sync_ts: Optional[str] = None) -> int:
    """
    Entry point for syncing profiles of a given segment
    from ArangoDB into PostgreSQL.
    
    Args:
        tenant_id: The tenant identifier.
        segment_id: The segment identifier (optional).
        segment_name: The segment name (optional).
        last_sync_ts: The timestamp of the last sync (optional).
    Returns:
        int: The number of profiles synced.
    """

    logger.info("Starting sync for segment: %s tenant_id: %s segment_id: %s last_sync_ts: %s", segment_name, tenant_id, segment_id, last_sync_ts)

    # --- Infrastructure wiring ---
    settings = DatabaseSettings()
    arango_db = get_arango_db(settings)
    pg_conn = get_pg_connection(settings)
    
    # --- Tenant context ---
    tenant_id = resolve_and_set_default_tenant(pg_conn)

    # --- Repositories ---
    arango_repo = ArangoProfileRepository(arango_db, batch_size=500)
    pg_repo = PGProfileRepository(pg_conn)

    # --- Service ---
    sync_service = ArangoToPostgresSyncService(
        arango_repo=arango_repo,
        pg_repo=pg_repo,
        tenant_id=tenant_id,
    )

    # --- Execute ---
    synced_count = sync_service.sync_segment(tenant_id, segment_id , segment_name, last_sync_ts)

    logger.info(
        "Sync completed for segment '%s'. Profiles synced: %d",
        segment_name,
        synced_count,
    )

    return synced_count

