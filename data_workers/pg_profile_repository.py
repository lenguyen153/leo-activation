from data_models.pg_profile import PGProfileUpsert
import psycopg


# PostgreSQL repository for profiles (write side)
class PGProfileRepository:
    def __init__(self, conn: psycopg.Connection):
        self.conn = conn

    def upsert_profile(self, profile: PGProfileUpsert) -> None:
        """
        Upsert a CDP profile synced from ArangoDB.

        Design rules:
        - profile_id comes from Arango `_key`
        - JSON-like fields are written as JSONB
        - AI / portfolio fields are NOT touched here
        - ext_data is allowed for forward compatibility
        """

        sql = """
        INSERT INTO cdp_profiles (
            tenant_id,
            profile_id,

            -- identities
            identities,

            -- contact
            primary_email,
            secondary_emails,
            primary_phone,
            secondary_phones,

            -- personal & location
            first_name,
            last_name,
            living_location,
            living_country,
            living_city,

            -- enrichment
            job_titles,
            data_labels,
            content_keywords,
            media_channels,
            behavioral_events,

            -- segmentation & journeys
            segments,
            journey_maps,

            -- statistics & touchpoints
            event_statistics,
            top_engaged_touchpoints,

            -- extensibility
            ext_data
        )
        VALUES (
            %(tenant_id)s,
            %(profile_id)s,

            %(identities)s::jsonb,

            %(primary_email)s,
            %(secondary_emails)s::jsonb,
            %(primary_phone)s,
            %(secondary_phones)s::jsonb,

            %(first_name)s,
            %(last_name)s,
            %(living_location)s,
            %(living_country)s,
            %(living_city)s,

            %(job_titles)s::jsonb,
            %(data_labels)s::jsonb,
            %(content_keywords)s::jsonb,
            %(media_channels)s::jsonb,
            %(behavioral_events)s::jsonb,

            %(segments)s::jsonb,
            %(journey_maps)s::jsonb,

            %(event_statistics)s::jsonb,
            %(top_engaged_touchpoints)s::jsonb,

            %(ext_data)s::jsonb
        )
        ON CONFLICT (tenant_id, profile_id)
        DO UPDATE SET
            identities = EXCLUDED.identities,

            primary_email = EXCLUDED.primary_email,
            secondary_emails = EXCLUDED.secondary_emails,
            primary_phone = EXCLUDED.primary_phone,
            secondary_phones = EXCLUDED.secondary_phones,

            first_name = EXCLUDED.first_name,
            last_name = EXCLUDED.last_name,
            living_location = EXCLUDED.living_location,
            living_country = EXCLUDED.living_country,
            living_city = EXCLUDED.living_city,

            job_titles = EXCLUDED.job_titles,
            data_labels = EXCLUDED.data_labels,
            content_keywords = EXCLUDED.content_keywords,
            media_channels = EXCLUDED.media_channels,
            behavioral_events = EXCLUDED.behavioral_events,

            segments = EXCLUDED.segments,
            journey_maps = EXCLUDED.journey_maps,

            event_statistics = EXCLUDED.event_statistics,
            top_engaged_touchpoints = EXCLUDED.top_engaged_touchpoints,

            ext_data = EXCLUDED.ext_data;
        """

        with self.conn.cursor() as cur:
            cur.execute(sql, profile.to_pg_row())

        self.conn.commit()
