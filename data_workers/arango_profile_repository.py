# repositories/arango_profile_repository.py
import logging
from typing import List, Optional

from data_models.arango_profile import CDP_PROFILE_QUERY, ArangoProfile


logger = logging.getLogger(__name__)


class ArangoProfileRepository:
    def __init__(self, db, batch_size: int = 1000):
        self.db = db
        self.batch_size = batch_size

    def resolve_segment_id(self, segment_name: str) -> str | None:
        query = """
        FOR s IN cdp_segment
            FILTER s.name == @name AND s.status == 1
            SORT s.totalCount DESC
            LIMIT 1
            RETURN s._key
        """
        cursor = self.db.aql.execute(query, bind_vars={"name": segment_name})
        return next(iter(cursor), None)

    def fetch_profiles_by_segment(self, segment_id: Optional[str] = None, segment_name: Optional[str] = None, start_index: int = 0) -> List[ArangoProfile]:
        if not segment_id and segment_name:
            segment_id = self.resolve_segment_id(segment_name)
            logger.info(
                "[ArangoDB] Resolving segment ID for name %s -> %s",
                segment_name,
                segment_id,
            )

        if not segment_id:
            logger.warning("[ArangoDB] Segment not found: %s", segment_name)
            return []


        cursor = self.db.aql.execute(
            CDP_PROFILE_QUERY, bind_vars={"segment_id": segment_id, "batch_size": self.batch_size, "start_index": start_index}
        )

        profiles: List[ArangoProfile] = []

        for doc in cursor:
            try:
                profiles.append(ArangoProfile.from_arango(doc))  # ✅ THE FIX
            except Exception:
                logger.exception(
                    "[ArangoDB] Failed to parse profile %s",
                    doc.get("_key"),
                )

        logger.info("[ArangoDB] Loaded %d profiles", len(profiles))
        return profiles
