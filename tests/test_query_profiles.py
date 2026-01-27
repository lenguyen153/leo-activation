from data_models.dbo_tenant import get_default_tenant_id
from data_workers.pg_profile_repository import PGProfileRepository
from data_utils.settings import DatabaseSettings
from data_utils.pg_client import get_pg_connection

import logging
import sys
import json
from typing import Optional

# Ensure project root is on path
import os
sys.path.insert(0, os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..")))


logger = logging.getLogger(__name__)


def run_repository_tests(pg_repo: PGProfileRepository, tenant_id: str) -> None:
    """
    Executes the 12 new search/load functions against the database
    using the initialized repository.
    """
    logger.info(f"--- STARTING TESTS FOR TENANT: {tenant_id} ---")

    # =========================================================
    # 1. Segment or Journey
    # =========================================================
    logger.info("--- 1. Load by Segment/Journey ---")
    res = pg_repo.load_profiles_by_segment_or_journey(
        tenant_id, segment_id="VIP")
    logger.info(f"   [Segment 'VIP']: Found {len(res)} profiles")

    res = pg_repo.load_profiles_by_segment_or_journey(
        tenant_id, journey_id="J01")
    logger.info(f"   [Journey 'J01']: Found {len(res)} profiles")

    # =========================================================
    # 2. Data Labels
    # =========================================================
    logger.info("--- 2. Search by Data Label ---")
    res = pg_repo.search_profiles_by_data_label(tenant_id, "HIGH_NET_WORTH")
    logger.info(f"   [Label 'HIGH_NET_WORTH']: Found {len(res)} profiles")

    # =========================================================
    # 3. Email (Primary or Secondary)
    # =========================================================
    logger.info("--- 3. Load by Email ---")
    test_email = "nam@gmail.com"
    res = pg_repo.load_profile_by_email(tenant_id, test_email)
    logger.info(f"   [Email '{test_email}']: Found {len(res)} profiles")

    # =========================================================
    # 4. Phone (Primary or Secondary)
    # =========================================================
    logger.info("--- 4. Load by Phone ---")
    test_phone = "+84901234567"
    res = pg_repo.load_profile_by_phone(tenant_id, test_phone)
    logger.info(f"   [Phone '{test_phone}']: Found {len(res)} profiles")

    # =========================================================
    # 5. Identities
    # =========================================================
    logger.info("--- 5. Load by Identity ---")
    test_identity = "crm:12345"
    res = pg_repo.load_profiles_by_identity(tenant_id, test_identity)
    logger.info(f"   [Identity '{test_identity}']: Found {len(res)} profiles")

    # =========================================================
    # 6. Living City
    # =========================================================
    logger.info("--- 6. Search by Living City ---")
    test_city = "Ho Chi Minh City"
    res = pg_repo.search_profiles_by_living_city(tenant_id, test_city)
    logger.info(f"   [City '{test_city}']: Found {len(res)} profiles")

    # =========================================================
    # 7. Content Keywords
    # =========================================================
    logger.info("--- 7. Search by Content Keywords ---")
    test_kw = "dividends"
    res = pg_repo.search_profiles_by_content_keyword(tenant_id, test_kw)
    logger.info(f"   [Keyword '{test_kw}']: Found {len(res)} profiles")

    # =========================================================
    # 8. Media Channels
    # =========================================================
    logger.info("--- 8. Search by Media Channels ---")
    test_channel = "ZALO"
    res = pg_repo.search_profiles_by_media_channel(tenant_id, test_channel)
    logger.info(f"   [Channel '{test_channel}']: Found {len(res)} profiles")

    # =========================================================
    # 9. Behavioral Events (Tags)
    # =========================================================
    logger.info("--- 9. Search by Behavioral Event Tag ---")
    test_event = "VIEW_STOCK"
    res = pg_repo.search_profiles_by_behavioral_event_label(
        tenant_id, test_event)
    logger.info(f"   [Event '{test_event}']: Found {len(res)} profiles")

    # =========================================================
    # 10. Event Statistics
    # =========================================================
    logger.info("--- 10. Search by Event Statistics Key ---")
    test_stat = "CLICK"
    res = pg_repo.search_profiles_by_event_statistic_key(tenant_id, test_stat)
    logger.info(f"   [Stat Key '{test_stat}']: Found {len(res)} profiles")

    # =========================================================
    # 11. Top Engaged Touchpoints
    # =========================================================
    logger.info("--- 11. Search by Top Touchpoint ID ---")
    test_tp = "tp_01"
    res = pg_repo.search_profiles_by_touchpoint_key(tenant_id, test_tp)
    logger.info(f"   [Touchpoint '{test_tp}']: Found {len(res)} profiles")

    # =========================================================
    # 12. Job Titles
    # =========================================================
    logger.info("--- 12. Search by Job Title ---")
    test_job = "Investor"
    res = pg_repo.search_profiles_by_job_title(tenant_id, test_job)
    logger.info(f"   [Job '{test_job}']: Found {len(res)} profiles")


def main(argv: Optional[list[str]] = None) -> None:
    argv = argv or sys.argv[1:]

    # Optional CLI override for tenant_id
    cli_tenant_id = argv[0] if argv else None

    logger.info("Initializing Test Harness...")

    try:
        # --- Infrastructure wiring ---
        pg_conn = DatabaseSettings().get_pg_connection()

        # --- Tenant context ---
        # If not provided via CLI, resolve default from DB
        if cli_tenant_id:
            tenant_id = cli_tenant_id
        else:
            tenant_id = get_default_tenant_id()

        if not tenant_id:
            logger.error( "Could not resolve Tenant ID. Please provide one or check your 'tenant' table.")
            sys.exit(1)

        # --- Repository ---
        pg_repo = PGProfileRepository(pg_conn)

        # --- Execute Tests ---
        run_repository_tests(pg_repo, tenant_id)

    except Exception as exc:
        logger.exception("Test execution failed: %s", exc)
        sys.exit(1)
    finally:
        # Close connection if it exists and is open
        if 'pg_conn' in locals() and pg_conn:
            pg_conn.close()


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s - %(message)s",
    )
    main()
