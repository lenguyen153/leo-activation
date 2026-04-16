"""
Backfill primary_email from identities column in cdp_profiles.

Finds all profiles where primary_email IS NULL but identities contains
an "email:..." entry, extracts the address, and writes it to primary_email.
"""
from dotenv import load_dotenv

load_dotenv()

from data_utils.logging_config import configure_logging, get_logger, log_event
from data_utils.settings import DatabaseSettings

configure_logging()
logger = get_logger(__name__)

SQL_BACKFILL = """
UPDATE cdp_profiles
SET primary_email = sub.email
FROM (
    SELECT
        profile_id,
        tenant_id,
        elem AS email
    FROM cdp_profiles,
         jsonb_array_elements_text(identities) AS elem
    WHERE elem LIKE 'email:%%'
      AND primary_email IS NULL
) AS sub
WHERE cdp_profiles.profile_id = sub.profile_id
  AND cdp_profiles.tenant_id  = sub.tenant_id
RETURNING cdp_profiles.profile_id, cdp_profiles.primary_email;
"""

# Strip the "email:" prefix — Postgres expression used in the UPDATE itself
SQL_BACKFILL = """
UPDATE cdp_profiles
SET primary_email = SUBSTRING(sub.email FROM 7)
FROM (
    SELECT
        profile_id,
        tenant_id,
        elem AS email
    FROM cdp_profiles,
         jsonb_array_elements_text(identities) AS elem
    WHERE elem LIKE 'email:%%'
      AND primary_email IS NULL
) AS sub
WHERE cdp_profiles.profile_id = sub.profile_id
  AND cdp_profiles.tenant_id  = sub.tenant_id
RETURNING cdp_profiles.profile_id, cdp_profiles.primary_email;
"""


def run():
    settings = DatabaseSettings()
    conn = settings.get_pg_connection()

    try:
        with conn.cursor() as cur:
            cur.execute(SQL_BACKFILL)
            rows = cur.fetchall()
        conn.commit()

        log_event(logger, "primary_email_backfill_complete", updated=len(rows))
        for r in rows[:20]:
            logger.info("  profile_id=%-36s  primary_email=%s", r["profile_id"], r["primary_email"])
        if len(rows) > 20:
            logger.info("  ... and %d more.", len(rows) - 20)

    except Exception as e:
        conn.rollback()
        logger.error("Backfill failed: %s", e)
        raise
    finally:
        conn.close()


if __name__ == "__main__":
    run()
