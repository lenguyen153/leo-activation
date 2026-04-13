"""
Scoring Consumer — main loop.

Reads CdpEventMessage from `cdp.events.raw`, resolves fingerprint→profile,
computes incremental score, upserts to PG, and publishes ScoreUpdateMessage
to `leo.score.updates`.
"""

import datetime
import json
import logging
import os
import signal
import sys
import time
from concurrent.futures import ThreadPoolExecutor

import redis
import requests
from prometheus_client import Counter, Histogram, start_http_server

from agentic_tools.recommendation_system.interest_score import (
    HALF_LIFE_DAYS,
    SCORING_K_FACTOR,
    compute_incremental_score,
    resolve_ids,
    TARGET_TENANT,
    TARGET_SEGMENT,
)
from services.scoring_consumer.config import (
    CONSUMER_GROUP,
    DLQ_TOPIC,
    EVENT_FORWARD_URL,
    INPUT_TOPIC,
    KAFKA_BOOTSTRAP_SERVERS,
    MAX_RETRIES,
    OUTPUT_TOPIC,
    REALTIME_SCORING_ENABLED,
    REDIS_URL,
)
from services.scoring_consumer.pg_writer import (
    fetch_base_account_id,
    fetch_existing_score,
    get_connection,
    reset_connection,
    upsert_score,
    validate_profile,
)
from services.shared.kafka_utils import create_consumer, create_producer
from services.shared.schemas import CdpEventMessage, ScoredEventForward, ScoreUpdateMessage

logger = logging.getLogger(__name__)

# --- Prometheus Metrics ---
EVENTS_PROCESSED = Counter("scoring_events_processed_total", "Total events processed by scoring consumer")
SCORING_LATENCY = Histogram("scoring_latency_seconds", "Per-message scoring latency")
SCORING_ERRORS = Counter("scoring_errors_total", "Total scoring errors")

_running = True
_tenant_id_cache: str | None = None
_forward_pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix="event-fwd")
FORWARD_ERRORS = Counter("scoring_forward_errors_total", "HTTP forward failures")


def _forward_scored_event(payload_json: str) -> None:
    """POST enriched event to external API (runs in background thread)."""
    try:
        requests.post(EVENT_FORWARD_URL, data=payload_json,
                      headers={"Content-Type": "application/json"}, timeout=5)
    except Exception:
        FORWARD_ERRORS.inc()
        logger.exception("Event forward POST failed")


def _resolve_tenant_id(conn) -> str:
    """Resolve and cache tenant UUID."""
    global _tenant_id_cache
    if _tenant_id_cache is None:
        tenant_uuid, _ = resolve_ids(conn, TARGET_TENANT, TARGET_SEGMENT)
        _tenant_id_cache = str(tenant_uuid)
    return _tenant_id_cache


def _resolve_fingerprint(r: redis.Redis, fingerprint_id: str) -> str | None:
    """Lookup profile_id from fingerprint via Redis cache."""
    return r.get(f"fp:{fingerprint_id}")


def _handle_signal(signum, frame):
    global _running
    logger.info("Received signal %d, shutting down...", signum)
    _running = False


def _send_to_dlq(producer, topic: str, raw_value: bytes, error: str) -> None:
    """Publish failed message to dead-letter queue."""
    dlq_payload = {
        "original_topic": topic,
        "original_value": raw_value.decode("utf-8", errors="replace"),
        "error": str(error),
        "timestamp": datetime.datetime.now(datetime.timezone.utc).isoformat(),
    }
    producer.produce(
        topic=DLQ_TOPIC,
        value=json.dumps(dlq_payload).encode("utf-8"),
    )
    producer.flush(timeout=5)


def main():
    global _running
    signal.signal(signal.SIGTERM, _handle_signal)
    signal.signal(signal.SIGINT, _handle_signal)

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
    )

    # Start Prometheus metrics server
    start_http_server(8081)
    logger.info("Prometheus metrics server started on :8081")

    dry_run = not REALTIME_SCORING_ENABLED
    if dry_run:
        logger.warning("REALTIME_SCORING_ENABLED=False — dry-run mode (consume but don't write)")

    r = redis.from_url(REDIS_URL, decode_responses=True)
    consumer = create_consumer(CONSUMER_GROUP, [INPUT_TOPIC], KAFKA_BOOTSTRAP_SERVERS)
    producer = create_producer(KAFKA_BOOTSTRAP_SERVERS)

    logger.info("Scoring consumer started. Group=%s Topic=%s", CONSUMER_GROUP, INPUT_TOPIC)

    while _running:
        msg = consumer.poll(timeout=1.0)
        if msg is None:
            continue
        if msg.error():
            logger.error("Consumer error: %s", msg.error())
            continue

        raw_value = msg.value()
        retries = 0

        while retries <= MAX_RETRIES:
            try:
                conn = get_connection()

                with SCORING_LATENCY.time():
                    event = CdpEventMessage.model_validate_json(raw_value)

                    # 1. Resolve fingerprint → profile_id
                    profile_id = _resolve_fingerprint(r, event.fingerprint_id)
                    if not profile_id:
                        logger.debug("No profile mapping for fingerprint %s, skipping", event.fingerprint_id)
                        break

                    # 2. Resolve tenant
                    tenant_id = _resolve_tenant_id(conn)

                    # 3. Validate profile exists in PG
                    if not validate_profile(conn, profile_id):
                        logger.debug("Profile %s not in PG, skipping", profile_id)
                        break

                    if dry_run:
                        logger.info("[DRY-RUN] Would score %s/%s", profile_id, event.ticker)
                        EVENTS_PROCESSED.inc()
                        break

                    # 4. Read current score
                    existing = fetch_existing_score(conn, tenant_id, profile_id, event.ticker)

                    if existing:
                        current_raw = float(existing["raw_score"] or 0.0)
                        prev_interest = float(existing["interest_score"] or 0.0)
                        prev_interaction = existing["last_interaction_at"]
                        if not prev_interaction:
                            prev_interaction = datetime.datetime.now(datetime.timezone.utc)
                    else:
                        current_raw = 0.0
                        prev_interest = 0.0
                        prev_interaction = None

                    last_event_time = datetime.datetime.fromisoformat(
                        event.created_at.replace("Z", "+00:00")
                    )

                    # 5. Compute incremental score
                    new_raw, new_interest = compute_incremental_score(
                        current_raw, event.metric_score, prev_interaction, last_event_time
                    )

                    # 6. Upsert to PG
                    upsert_score(conn, tenant_id, profile_id, event.ticker, new_raw, new_interest, last_event_time)

                    # 7. Publish ScoreUpdateMessage
                    score_delta = new_interest - prev_interest
                    base_account_id = fetch_base_account_id(conn, profile_id)
                    update_msg = ScoreUpdateMessage(
                        tenant_id=tenant_id,
                        profile_id=profile_id,
                        base_account_id=base_account_id,
                        ticker=event.ticker,
                        metric_name=event.metric_name,
                        interest_score=new_interest,
                        raw_score=new_raw,
                        score_delta=score_delta,
                        updated_at=datetime.datetime.now(datetime.timezone.utc).isoformat(),
                    )
                    producer.produce(
                        topic=OUTPUT_TOPIC,
                        key=f"{profile_id}:{event.ticker}".encode("utf-8"),
                        value=update_msg.model_dump_json().encode("utf-8"),
                    )
                    producer.flush(timeout=5)

                    # 8. Forward enriched event via HTTP POST (fire-and-forget)
                    if EVENT_FORWARD_URL:
                        fwd = ScoredEventForward(
                            event_key=event.event_key,
                            profile_id=profile_id,
                            ticker=event.ticker,
                            metric_name=event.metric_name,
                            metric_score=event.metric_score,
                            interest_score=new_interest,
                            raw_score=new_raw,
                            score_delta=score_delta,
                            created_at=event.created_at,
                            event_data=event.event_data,
                        )
                        _forward_pool.submit(_forward_scored_event, fwd.model_dump_json())

                    EVENTS_PROCESSED.inc()
                    logger.info(
                        "Scored %s/%s: raw=%.2f interest=%.4f delta=%.4f",
                        profile_id, event.ticker, new_raw, new_interest, score_delta,
                    )

                # Success — break retry loop
                break

            except Exception as e:
                retries += 1
                SCORING_ERRORS.inc()
                # Reconnect PG on any failure (connection may be stale)
                try:
                    reset_connection()
                except Exception:
                    pass
                if retries > MAX_RETRIES:
                    logger.error("Max retries exceeded for message, sending to DLQ: %s", e)
                    _send_to_dlq(producer, INPUT_TOPIC, raw_value, str(e))
                    break
                logger.warning("Retry %d/%d for message: %s", retries, MAX_RETRIES, e)
                time.sleep(0.5 * retries)

        # Commit offset after processing (success or DLQ)
        consumer.commit(asynchronous=False)

    _forward_pool.shutdown(wait=True, cancel_futures=False)
    consumer.close()
    try:
        get_connection().close()
    except Exception:
        pass
    logger.info("Scoring consumer shut down.")


if __name__ == "__main__":
    main()
