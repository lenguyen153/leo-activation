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

    def sync_segment(self,  tenant_id: Optional[str] = None,
                     segment_id: Optional[str] = None,
                     segment_name: Optional[str] = None,
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

        total_synched_profile = 0
        start = 0
        cdp_profiles = self.arango_repo.fetch_profiles_by_segment(
            segment_id=segment_id, segment_name=segment_name, start_index=start)
        size = len(cdp_profiles)

        if size == 0:
            logger.info(
                "[SyncService] No profiles found for segment_id=%s, segment_name=%s", segment_id, segment_name)
            return 0
        else:
            logger.info("[SyncService] Fetched %d profiles for segment_id=%s, segment_name=%s",
                        size, segment_id, segment_name)

            while size > 0:
                for p in cdp_profiles:
                    logger.info(f"Syncing profile: {p.profile_id}")

                    pg_profile = self.to_pg_profile(
                        segment_id, segment_name, p)

                    self.pg_repo.upsert_profile(pg_profile)
                    total_synched_profile += 1

                start = self.arango_repo.batch_size + start
                print(f"Synced profiles at start: {start}")
                cdp_profiles = self.arango_repo.fetch_profiles_by_segment(segment_id=segment_id, segment_name=segment_name, start_index=start)
                size = len(cdp_profiles)

        return total_synched_profile

    def to_pg_profile(self, segment_id, segment_name, p):
 
        pg_profile = PGProfileUpsert(
            tenant_id=self.tenant_id,
            profile_id=p.profile_id or "",
            # -------------------------
            # identity
            # -------------------------
            identities=p.identities,
            # -------------------------
            # contact (already sanitized in ArangoProfile)
            # -------------------------
            primary_email=p.primaryEmail,
            secondary_emails=p.secondaryEmails,
            primary_phone=p.primaryPhone,
            secondary_phones=p.secondaryPhones,
            # -------------------------
            # personal & location
            # -------------------------
            first_name=p.firstName,
            last_name=p.lastName,
            living_location=p.livingLocation,
            living_country=p.livingCountry,
            living_city=p.livingCity,
            # -------------------------
            # enrichment
            # -------------------------
            job_titles=p.jobTitles,
            data_labels=p.dataLabels,
            content_keywords=p.contentKeywords,
            media_channels=p.mediaChannels,
            behavioral_events=p.behavioralEvents,
            # -------------------------
            # segmentation & journeys
            # NOTE:
            #   p.inSegments is List[SegmentRef]
            #   PGProfileUpsert accepts dicts OR strings
            #   Canonicalization happens in validator
            # -------------------------
            segments=[
                {"id": s.id, "name": s.name}
                for s in p.inSegments
            ],
            journey_maps=[
                {
                    "id": j.id,
                    "name": j.name,
                    "funnelIndex": j.funnelIndex,
                }
                for j in p.inJourneyMaps
            ],
            # -------------------------
            # statistics & touchpoints
            # -------------------------
            event_statistics=p.eventStatistics,
            top_engaged_touchpoints=[
                {
                    "id": t.id,
                    "hostname": t.hostname,
                    "name": t.name,
                    "url": t.url,
                    "parentId": t.parentId,
                }
                for t in p.topEngagedTouchpoints
            ],
            # -------------------------
            # extensibility (replacement for raw_attributes)
            # -------------------------
            ext_data={
                "source": "arango",
                "sync_segment_id": segment_id,
                "sync_segment_name": segment_name,
            },
        )

        return pg_profile
