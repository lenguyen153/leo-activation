import logging
from typing import Optional
from data_models.pg_profile import PGProfileUpsert
from data_workers.arango_profile_repository import ArangoProfileRepository
from data_workers.pg_profile_repository import PGProfileRepository

logger = logging.getLogger(__name__)

class ArangoToPostgresSyncService:
    def __init__(
        self,
        arango_repo: ArangoProfileRepository,
        pg_repo: PGProfileRepository,
        tenant_id: str,
    ):
        self.arango_repo = arango_repo
        self.pg_repo = pg_repo
        self.tenant_id = tenant_id

    def sync_segment(self, segment_name: str, tenant_id: Optional[str] = None, 
                        segment_id: Optional[str] = None,                       
                        last_sync_ts: Optional[str] = None) -> int:
        """
        sync profiles of a given segment from ArangoDB into PostgreSQL.
        
        Args:
            tenant_id: The tenant identifier.
            segment_id: The segment identifier (optional).
            segment_name: The segment name (optional).
            last_sync_ts: The timestamp of the last sync (optional).
        Returns:
            int: The number of profiles synced.
        """
        
        cdp_profiles = self.arango_repo.fetch_profiles_by_segment(segment_name)

        count = 0
        for p in cdp_profiles:
            raw_attributes = {
                "dataLabels": ["test"]
            }
            logger.info(f"Syncing profile: {p}")
            pg_profile = PGProfileUpsert(
                tenant_id=self.tenant_id,
                profile_id=p.profile_id or "",
                email=p.primaryEmail,
                mobile_number=p.primaryPhone,
                first_name=p.firstName,
                last_name=p.lastName,
                job_title=p.jobTitles[0] if p.jobTitles else None,
                segments=[s.name for s in p.inSegments],
                raw_attributes=raw_attributes
            )
            self.pg_repo.upsert_profile(pg_profile)
            count += 1

        return count
