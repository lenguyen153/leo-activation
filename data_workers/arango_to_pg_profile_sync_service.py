from data_models.pg_profile import PGProfileUpsert
from data_workers.arango_profile_repo import ArangoProfileRepository
from data_workers.pg_profile_repository import PGProfileRepository


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

    def sync_segment(self, segment_name: str) -> int:
        segment_id = self.arango_repo.resolve_segment_id(segment_name)
        profiles = self.arango_repo.fetch_profiles_by_segment(segment_id)

        count = 0
        for p in profiles:
            pg_profile = PGProfileUpsert(
                tenant_id=self.tenant_id,
                profile_id=p.profile_id or "",
                email=p.primaryEmail,
                mobile_number=p.primaryPhone,
                first_name=p.firstName,
                last_name=p.lastName,
                job_title=p.jobTitles[0] if p.jobTitles else None,
                segments=[s.name for s in p.inSegments],
                raw_attributes=p.raw,
            )
            self.pg_repo.upsert_profile(pg_profile)
            count += 1

        return count
