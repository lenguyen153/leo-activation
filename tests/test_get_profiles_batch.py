

import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from typing import Generator, List
from sqlalchemy import select
from sqlalchemy.orm import Session
from data_utils.db_factory import get_db_context
from data_utils.settings import DatabaseSettings
from data_models.dbo_cdp import CdpProfile


def get_profiles_in_journey_batched(
    session: Session,
    journey_id: str,
    batch_size: int = 10
) -> Generator[List[CdpProfile], None, None]:
    """
    Generator that yields batches of CdpProfiles belonging to a specific journey.

    Args:
        session: Active DB session
        journey_id: The ID to search for inside the JSONB array (e.g., 'J01')
        batch_size: Number of records per batch
    """

    # 1. Create the JSONB Filter
    # SQL Equivalent: journey_maps @> '[{"id": "J01"}]'
    # We pass a Python list/dict structure that matches the JSON subset we want.
    json_filter = CdpProfile.journey_maps.contains([{"id": journey_id}])

    offset = 0

    while True:
        # 2. Build the Query
        stmt = (
            select(CdpProfile)
            .where(json_filter)
            # Ordering is crucial for pagination stability
            .order_by(CdpProfile.profile_id)
            .limit(batch_size)
            .offset(offset)
        )

        # 3. Execute
        # .scalars() extracts the CdpProfile objects from the Row tuples
        results = session.execute(stmt).scalars().all()

        # 4. Break if no data left
        if not results:
            break

        yield results

        # Optimization: If we got fewer rows than requested, we are at the end.
        if len(results) < batch_size:
            break

        # 5. Advance Offset
        offset += batch_size


# --- Execution ---
if __name__ == "__main__":
    settings = DatabaseSettings()

    TARGET_JOURNEY = "J01"

    print(f"--- Searching for profiles in Journey: {TARGET_JOURNEY} ---")

    with get_db_context(settings) as session:
        batch_generator = get_profiles_in_journey_batched(
            session,
            journey_id=TARGET_JOURNEY,
            batch_size=2
        )

        total_count = 0

        for i, batch in enumerate(batch_generator, 1):
            print(f"Processing Batch {i} (Size: {len(batch)})")

            for profile in batch:
                # Assuming journey_maps looks like [{"id": "J01", "name": "..."}]
                # We extract the specific journey data for display
                journey_info = next(
                    (j for j in profile.journey_maps if j.get(
                        "id") == TARGET_JOURNEY),
                    {}
                )

                print(f"  - User: {profile.primary_email} | Status: {journey_info.get('name', 'Unknown')}")

            total_count += len(batch)
            print("-" * 40)

        print(f"Total Profiles Processed: {total_count}")
