
from typing import List, Optional, Dict, Any
from data_models.pg_profile import PGProfileUpsert
import psycopg
import json

UPSERT_PROFILE_SQL = """
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


class PGProfileRepository:
    """ 
        PostgreSQL repository for profiles management.
    """

    def __init__(self, conn: psycopg.Connection):
        self.conn = conn

    def _execute_fetch(self, query: str, params: tuple) -> List[Dict[str, Any]]:
        """
        Helper to execute a query and return results as a list of dictionaries.
        """
        with self.conn.cursor(row_factory=psycopg.rows.dict_row) as cur:
            cur.execute(query, params)
            return cur.fetchall()

    # =========================================================================
    # 0. Upsert profile
    # ========================================================================= 
    def upsert_profile(self, profile: PGProfileUpsert) -> None:
        """
        Upsert a CDP profile synced from ArangoDB.

        Design rules:
        - profile_id comes from Arango `_key`
        - JSON-like fields are written as JSONB
        - AI / portfolio fields are NOT touched here
        - ext_data is allowed for forward compatibility
        """

        with self.conn.cursor() as cur:
            cur.execute(UPSERT_PROFILE_SQL, profile.to_pg_row())

        self.conn.commit()

    # =========================================================================
    # 1. Load profiles by segment_id or journey_map_id
    # =========================================================================
    def load_profiles_by_segment_or_journey(self, tenant_id: str, segment_id: str = None, journey_id: str = None) -> List[Dict[str, Any]]:
        """
        Finds profiles belonging to a specific segment ID or journey ID.
        Both columns are JSONB arrays of objects like [{"id": "X", ...}].
        """
        if segment_id:
            sql = """
                SELECT * FROM cdp_profiles 
                WHERE tenant_id = %s 
                AND segments @> %s::jsonb
            """
            # Construct JSONB filter: matches any object in array with "id": segment_id
            param_json = json.dumps([{"id": segment_id}])
            return self._execute_fetch(sql, (tenant_id, param_json))

        if journey_id:
            sql = """
                SELECT * FROM cdp_profiles 
                WHERE tenant_id = %s 
                AND journey_maps @> %s::jsonb
            """
            param_json = json.dumps([{"id": journey_id}])
            return self._execute_fetch(sql, (tenant_id, param_json))

        return []

    # =========================================================================
    # 2. Search profiles by data_labels
    # =========================================================================
    def search_profiles_by_data_label(self, tenant_id: str, label: str) -> List[Dict[str, Any]]:
        """
        Finds profiles having a specific data label (e.g., 'VIP', 'WHALE').
        data_labels is a JSONB array of strings.
        """
        sql = """
            SELECT * FROM cdp_profiles 
            WHERE tenant_id = %s 
            AND data_labels ? %s
        """
        return self._execute_fetch(sql, (tenant_id, label))

    # =========================================================================
    # 3. Load profile by email (Primary or Secondary)
    # =========================================================================
    def load_profile_by_email(self, tenant_id: str, email: str) -> List[Dict[str, Any]]:
        """
        Searches primary_email (CITEXT) and secondary_emails (JSONB array).
        """
        sql = """
            SELECT * FROM cdp_profiles 
            WHERE tenant_id = %s 
            AND (
                primary_email = %s 
                OR secondary_emails @> %s::jsonb
            )
        """
        # For secondary_emails array containment check
        emails_json = json.dumps([email])
        return self._execute_fetch(sql, (tenant_id, email, emails_json))

    # =========================================================================
    # 4. Load profile by phone (Primary or Secondary)
    # =========================================================================
    def load_profile_by_phone(self, tenant_id: str, phone: str) -> List[Dict[str, Any]]:
        """
        Searches primary_phone (TEXT) and secondary_phones (JSONB array).
        """
        sql = """
            SELECT * FROM cdp_profiles 
            WHERE tenant_id = %s 
            AND (
                primary_phone = %s 
                OR secondary_phones @> %s::jsonb
            )
        """
        phones_json = json.dumps([phone])
        return self._execute_fetch(sql, (tenant_id, phone, phones_json))

    # =========================================================================
    # 5. Load profiles by identities
    # =========================================================================
    def load_profiles_by_identity(self, tenant_id: str, identity_string: str) -> List[Dict[str, Any]]:
        """
        Finds profiles linking to a specific external ID (e.g., 'crm:12345').
        identities is a JSONB array of strings.
        """
        sql = """
            SELECT * FROM cdp_profiles 
            WHERE tenant_id = %s 
            AND identities ? %s
        """
        return self._execute_fetch(sql, (tenant_id, identity_string))

    # =========================================================================
    # 6. Search profiles by living_city
    # =========================================================================
    def search_profiles_by_living_city(self, tenant_id: str, city: str) -> List[Dict[str, Any]]:
        """
        Exact match on living_city.
        """
        sql = """
            SELECT * FROM cdp_profiles 
            WHERE tenant_id = %s 
            AND living_city = %s
        """
        return self._execute_fetch(sql, (tenant_id, city))

    # =========================================================================
    # 7. Search profiles by content_keywords
    # =========================================================================
    def search_profiles_by_content_keyword(self, tenant_id: str, keyword: str) -> List[Dict[str, Any]]:
        """
        Finds profiles interested in a specific keyword (e.g., 'dividends').
        content_keywords is a JSONB array of strings.
        """
        sql = """
            SELECT * FROM cdp_profiles 
            WHERE tenant_id = %s 
            AND content_keywords ? %s
        """
        return self._execute_fetch(sql, (tenant_id, keyword))

    # =========================================================================
    # 8. Search profiles by media_channels
    # =========================================================================
    def search_profiles_by_media_channel(self, tenant_id: str, channel: str) -> List[Dict[str, Any]]:
        """
        Finds profiles reachable via a specific channel (e.g., 'ZALO', 'EMAIL').
        media_channels is a JSONB array of strings.
        """
        sql = """
            SELECT * FROM cdp_profiles 
            WHERE tenant_id = %s 
            AND media_channels ? %s
        """
        return self._execute_fetch(sql, (tenant_id, channel))

    # =========================================================================
    # 9. Search profiles by behavioral_events
    # =========================================================================
    def search_profiles_by_behavioral_event_label(self, tenant_id: str, event_label: str) -> List[Dict[str, Any]]:
        """
        Finds profiles tagged with a semantic behavioral label (e.g., 'VIEW_STOCK').
        Note: This queries the 'behavioral_events' column on the profile (summary),
        not the raw event logs table.
        """
        sql = """
            SELECT * FROM cdp_profiles 
            WHERE tenant_id = %s 
            AND behavioral_events ? %s
        """
        return self._execute_fetch(sql, (tenant_id, event_label))

    # =========================================================================
    # 10. Search profiles by event_statistics
    # =========================================================================
    def search_profiles_by_event_statistic_key(self, tenant_id: str, stat_key: str) -> List[Dict[str, Any]]:
        """
        Finds profiles that have ANY statistics recorded for a specific key (e.g., 'CLICK').
        """
        sql = """
            SELECT * FROM cdp_profiles 
            WHERE tenant_id = %s 
            AND event_statistics ? %s
        """
        return self._execute_fetch(sql, (tenant_id, stat_key))

    # =========================================================================
    # 11. Search profiles by top_engaged_touchpoints
    # =========================================================================
    def search_profiles_by_touchpoint_key(self, tenant_id: str, touchpoint_key: str) -> List[Dict[str, Any]]:
        """
        Finds profiles where top_engaged_touchpoints contains a specific touchpoint key/id.
        top_engaged_touchpoints is an array of objects: [{"_key": "tp_01", ...}]
        """
        sql = """
            SELECT * FROM cdp_profiles 
            WHERE tenant_id = %s 
            AND top_engaged_touchpoints @> %s::jsonb
        """
        # Matches any object in the array having "_key": touchpoint_key
        param_json = json.dumps([{"_key": touchpoint_key}])
        return self._execute_fetch(sql, (tenant_id, param_json))

    # =========================================================================
    # 12. Search profiles by job_titles
    # =========================================================================
    def search_profiles_by_job_title(self, tenant_id: str, job_title: str) -> List[Dict[str, Any]]:
        """
        Finds profiles holding a specific job title.
        job_titles is a JSONB array of strings.
        """
        sql = """
            SELECT * FROM cdp_profiles 
            WHERE tenant_id = %s 
            AND job_titles ? %s
        """
        return self._execute_fetch(sql, (tenant_id, job_title))
