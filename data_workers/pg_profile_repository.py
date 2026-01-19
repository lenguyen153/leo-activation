from data_models.pg_profile import PGProfileUpsert
import psycopg


# PostgreSQL repository for profiles (write side)
class PGProfileRepository:
    def __init__(self, conn: psycopg.Connection):
        self.conn = conn

    def upsert_profile(self, profile: PGProfileUpsert) -> None:
        sql = """
        INSERT INTO cdp_profiles (
            tenant_id,
            profile_id,
            email,
            mobile_number,
            first_name,
            last_name,
            job_title,
            segments,
            raw_attributes
        )
        VALUES (
            %(tenant_id)s,
            %(profile_id)s,
            %(email)s,
            %(mobile_number)s,
            %(first_name)s,
            %(last_name)s,
            %(job_title)s,
            %(segments)s::jsonb,
            %(raw_attributes)s::jsonb
        )
        ON CONFLICT (profile_id)
        DO UPDATE SET
            email = EXCLUDED.email,
            mobile_number = EXCLUDED.mobile_number,
            first_name = EXCLUDED.first_name,
            last_name = EXCLUDED.last_name,
            job_title = EXCLUDED.job_title,
            segments = EXCLUDED.segments,
            raw_attributes = EXCLUDED.raw_attributes;
        """

        with self.conn.cursor() as cur:
            cur.execute(sql, profile.to_pg_row())

        self.conn.commit()
