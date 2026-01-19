import logging
from typing import List

from data_models.arango_profile import ArangoProfile

logger = logging.getLogger(__name__)

# ArangoDB repository for profiles (read side)
class ArangoProfileRepository:
    def __init__(self, db):
        self.db = db

    def resolve_segment_id(self, segment_name: str) -> str:
        query = """
        FOR s IN cdp_segment
            FILTER s.name == @name
            RETURN s._key
        """
        cursor = self.db.aql.execute(query, bind_vars={"name": segment_name})
        result = list(cursor)

        if not result:
            raise ValueError(f"Segment '{segment_name}' not found")

        return result[0]

    def fetch_profiles_by_segment(self, segment_id: str) -> List[ArangoProfile]:
        query = """
        FOR p IN cdp_profile
            FILTER @segment_id IN p.inSegments[*].id
            FILTER (p.primaryEmail != null AND p.primaryEmail != "")
               OR (p.primaryPhone != null AND p.primaryPhone != "")
            RETURN p
        """

        cursor = self.db.aql.execute(
            query, bind_vars={"segment_id": segment_id}
        )

        profiles: List[ArangoProfile] = []
        for doc in cursor:
            try:
                profiles.append(ArangoProfile.from_arango(doc))
            except Exception as e:
                logger.warning("Invalid profile skipped: %s", e)

        return profiles
