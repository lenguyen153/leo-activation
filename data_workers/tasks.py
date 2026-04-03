import logging
import os
from datetime import date, datetime, timezone
from typing import Optional

import redis
from celery import shared_task

from data_models.dbo_tenant import get_default_tenant_id
from data_workers.sync.sync_segment_profiles import run_synch_profiles
from main_configs import CELERY_REDIS_URL

# --------------------------------------------------
# Setup
# --------------------------------------------------



logger = logging.getLogger(__name__)
redis_client = redis.from_url(CELERY_REDIS_URL)


def _build_last_sync_key(
    *,
    segment_id: Optional[str] = None,
    segment_name: Optional[str] = None,
    tenant_id: Optional[str] = None
) -> str:
    """
    Build a deterministic Redis key for incremental sync checkpoints.
    """
    if segment_id:
        return f"leo_cdp:{tenant_id}:segment:{segment_id}:last_sync"
    return f"leo_cdp:{tenant_id}:segment_name:{segment_name}:last_sync"


# --------------------------------------------------
# Celery Task
# --------------------------------------------------

@shared_task(bind=True, autoretry_for=(Exception,), retry_backoff=30, retry_kwargs={"max_retries": 3})
def sync_profiles_task(
    self,
    *,
    segment_id: Optional[str] = None,
    segment_name: Optional[str] = None,
    tenant_id: Optional[str] = None,
) -> None:
    """
    Incremental Sync Task
    - Sync profiles by segment_id OR segment_name
    - Exactly one must be provided
    """

    if not tenant_id:
        tenant_id = get_default_tenant_id()

    # --------------------------------------------------
    # Validation (fail fast, fail loud)
    # --------------------------------------------------

    if bool(segment_id) == bool(segment_name):
        raise ValueError(
            "Exactly one of `segment_id` or `segment_name` must be provided."
        )

    logger.info(
        "Starting profile sync | tenant=%s | segment_id=%s | segment_name=%s",
        tenant_id,
        segment_id,
        segment_name,
    )

    # --------------------------------------------------
    # Load last checkpoint
    # --------------------------------------------------

    last_sync_key = _build_last_sync_key(
        segment_id=segment_id,
        segment_name=segment_name,
        tenant_id=tenant_id
    )

    last_sync_ts = redis_client.get(last_sync_key)
    if last_sync_ts:
        last_sync_ts = last_sync_ts.decode("utf-8")
    else:
        last_sync_ts = "1970-01-01T00:00:00Z"

    current_run_time = datetime.now(timezone.utc).isoformat()

    logger.info("Last sync timestamp: %s", last_sync_ts)

    # --------------------------------------------------
    # Execute sync
    # --------------------------------------------------

    try:
        run_synch_profiles(
            segment_id=segment_id,
            segment_name=segment_name,
            tenant_id=tenant_id,
            last_sync_ts=last_sync_ts,
        )

        # --------------------------------------------------
        # Persist checkpoint ONLY on success
        # --------------------------------------------------
        redis_client.set(last_sync_key, current_run_time)

        logger.info(
            "Sync completed | tenant=%s | segment=%s",
            tenant_id,
            segment_id or segment_name,
        )

    except Exception as exc:
        logger.exception("Profile sync failed")
        raise exc


# --------------------------------------------------
# Helpers
# --------------------------------------------------

def _fetch_stock_map(top_n: int = 20) -> dict:
    """Fetch top N stocks from the analysis API. Returns {symbol: StockRecommendation}."""
    import requests as _req
    from agentic_tools.channels.templates.zalo.models import StockRecommendation

    resp = _req.get(
        "https://news-analysis.innotech.vn/api/v1/stock/recommend_stock",
        params={"top_n": top_n},
        timeout=10,
    )
    resp.raise_for_status()
    raw = resp.json().get("recommendations", [])
    return {s["symbol"]: StockRecommendation(**s) for s in raw}


# --------------------------------------------------
# Zalo Promotional Dispatch
# --------------------------------------------------

@shared_task(bind=True, autoretry_for=(Exception,), retry_backoff=60, retry_kwargs={"max_retries": 2})
def zalo_promo_dispatch(self, *, tenant_id: Optional[str] = None) -> None:
    """Daily batch: send Zalo promotional messages to eligible users."""
    from agentic_tools.channels.zalo import ZaloOAChannel
    from agentic_tools.recommendation_system.interest_score import resolve_ids
    from data_utils.settings import DatabaseSettings

    settings = DatabaseSettings()
    conn = settings.get_pg_connection()
    target_tenant = os.getenv("TARGET_TENANT", "master")
    target_segment = os.getenv("TARGET_SEGMENT", "Active in last 3 months")
    today_str = date.today().isoformat()

    try:
        tenant_uuid, _ = resolve_ids(conn, target_tenant, target_segment)
        if tenant_id:
            tenant_uuid = tenant_id

        zalo = ZaloOAChannel(db_client=settings.get_arango_db())
        zalo.dispatch_promo_batch(conn, str(tenant_uuid), redis_client, today_str)
    except Exception as exc:
        conn.rollback()
        logger.exception("[Zalo Promo] Batch job failed")
        raise exc
    finally:
        conn.close()


# --------------------------------------------------
# Zalo Suggested Stock Dispatch
# --------------------------------------------------

@shared_task(bind=True, autoretry_for=(Exception,), retry_backoff=60, retry_kwargs={"max_retries": 2})
def zalo_suggested_stock_dispatch(self, *, tenant_id: Optional[str] = None) -> None:
    """Daily batch: send best-match stock pick to each interested Zalo follower."""
    from agentic_tools.channels.zalo import ZaloOAChannel
    from agentic_tools.recommendation_system.interest_score import resolve_ids
    from data_utils.settings import DatabaseSettings

    stock_map = _fetch_stock_map()
    if not stock_map:
        logger.info("[Zalo Suggested] No stocks returned from API. Aborting.")
        return
    logger.info("[Zalo Suggested] Fetched %d stocks from API.", len(stock_map))

    settings = DatabaseSettings()
    conn = settings.get_pg_connection()
    target_tenant = os.getenv("TARGET_TENANT", "master")
    target_segment = os.getenv("TARGET_SEGMENT", "Active in last 3 months")
    today_str = date.today().isoformat()

    try:
        tenant_uuid, _ = resolve_ids(conn, target_tenant, target_segment)
        if tenant_id:
            tenant_uuid = tenant_id

        zalo = ZaloOAChannel(db_client=settings.get_arango_db())
        zalo.dispatch_suggested_stock_batch(conn, str(tenant_uuid), redis_client, today_str, stock_map)
    except Exception as exc:
        conn.rollback()
        logger.exception("[Zalo Suggested] Batch job failed")
        raise exc
    finally:
        conn.close()


# --------------------------------------------------
# Email Suggested Stock Dispatch
# --------------------------------------------------

@shared_task(bind=True, autoretry_for=(Exception,), retry_backoff=60, retry_kwargs={"max_retries": 2})
def email_suggested_stock_dispatch(self, *, tenant_id: Optional[str] = None) -> None:
    """Daily batch: send personalised stock pick emails to all interested users."""
    from agentic_tools.channels.email import EmailChannel
    from agentic_tools.recommendation_system.interest_score import resolve_ids
    from data_utils.settings import DatabaseSettings

    stock_map = _fetch_stock_map()
    if not stock_map:
        logger.info("[Email Suggested] No stocks returned from API. Aborting.")
        return
    logger.info("[Email Suggested] Fetched %d stocks from API.", len(stock_map))

    settings = DatabaseSettings()
    conn = settings.get_pg_connection()
    target_tenant = os.getenv("TARGET_TENANT", "master")
    target_segment = os.getenv("TARGET_SEGMENT", "Active in last 3 months")
    today_str = date.today().isoformat()

    try:
        tenant_uuid, _ = resolve_ids(conn, target_tenant, target_segment)
        if tenant_id:
            tenant_uuid = tenant_id

        channel = EmailChannel()
        channel.dispatch_suggested_stock_batch(conn, str(tenant_uuid), redis_client, today_str, stock_map)
    except Exception as exc:
        conn.rollback()
        logger.exception("[Email Suggested] Batch job failed")
        raise exc
    finally:
        conn.close()


# --------------------------------------------------
# Portfolio Sync (Temporary — until CDC is restored)
# --------------------------------------------------

@shared_task(bind=True, autoretry_for=(Exception,), retry_backoff=60, retry_kwargs={"max_retries": 2})
def sync_active_users_portfolios_task(self, *, tenant_name: Optional[str] = None) -> None:
    """Temporary cronjob: sync portfolio data from FE events until CDC is restored."""
    from data_workers.sync.sync_active_users_portfolios import sync_active_users_portfolios

    result = sync_active_users_portfolios(tenant_name=tenant_name)
    logger.info(
        "[Portfolio Sync] %d portfolios, %d holdings, %d skipped",
        result["portfolios"], result["holdings"], result["skipped"],
    )
