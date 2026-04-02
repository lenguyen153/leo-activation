"""
NBA Publisher — main loop.

Reads ScoreUpdateMessage from `leo.score.updates`, runs predictive + prescriptive
engines, dispatches to marketing channels, and publishes NbaActionMessage.
"""

import datetime
import json
import logging
import signal
import time
from urllib.parse import quote_plus

import psycopg
import requests
from psycopg.rows import dict_row
from prometheus_client import Counter, Histogram, start_http_server

from agentic_tools.recommendation_system.predictive_engine import predict_user_event
from agentic_tools.recommendation_system.prescriptive_engine import recommend_system_action
from services.nba_publisher.config import (
    ACTIVATION_APP_WEBHOOK_URL,
    CONSUMER_GROUP,
    DLQ_TOPIC,
    INPUT_TOPIC,
    INTEREST_SCORE_THRESHOLD,
    KAFKA_BOOTSTRAP_SERVERS,
    MAX_RETRIES,
    OUTPUT_TOPIC,
    PGSQL_DB_HOST,
    PGSQL_DB_NAME,
    PGSQL_DB_PASSWORD,
    PGSQL_DB_PORT,
    PGSQL_DB_USER,
    REALTIME_SCORING_ENABLED,
    REDIS_URL,
    SCORE_DELTA_THRESHOLD,
)
from services.nba_publisher.throttle import is_throttled, set_throttle
from services.shared.kafka_utils import create_consumer, create_producer
from services.shared.schemas import NbaActionMessage, ScoreUpdateMessage

logger = logging.getLogger(__name__)

# --- Prometheus Metrics ---
NBA_DISPATCHES = Counter("nba_dispatches_total", "Total NBA dispatches", ["channel"])
NBA_THROTTLED = Counter("nba_throttled_total", "Total NBA dispatches throttled")
NBA_LATENCY = Histogram("nba_latency_seconds", "Per-message NBA processing latency")

# NBA UPDATE SQL — matches pattern from recommendation_orchestrator.py:86-98
_NBA_UPDATE_SQL = """
    UPDATE product_recommendations
    SET next_best_action = %s,
        nba_confidence = %s,
        predicted_user_event = %s,
        prediction_probability = %s,
        updated_at = NOW()
    WHERE tenant_id = %s
      AND profile_id = %s
      AND product_id = %s
      AND journey_map_id = %s
      AND journey_stage_id = %s
      AND recommendation_model = %s;
"""

# Dummy PK values (same as batch scoring)
DUMMY_JOURNEY_MAP_ID = "default_journey_map"
DUMMY_JOURNEY_STAGE_ID = "default_stage"
DUMMY_REC_MODEL = "default_model"

# Channel mapping: prescriptive engine output → dispatch action
# PUSH_NOTIFICATION → mobile_push/web_push, EMAIL_DIGEST → email, IN_APP_*/NONE → skip
_CHANNEL_MAP = {
    "PUSH_NOTIFICATION": ["mobile_push", "web_push"],
    "EMAIL_DIGEST": ["email"],
}

_running = True


def _build_dsn() -> str:
    encoded_pw = quote_plus(PGSQL_DB_PASSWORD)
    return (
        f"postgresql://{PGSQL_DB_USER}:{encoded_pw}@"
        f"{PGSQL_DB_HOST}:{PGSQL_DB_PORT}/"
        f"{PGSQL_DB_NAME}?options=-c%20search_path%3Dag_catalog,public"
    )


def _fetch_segments(conn, tenant_id: str, profile_id: str) -> list[str]:
    """Fetch segment names from cdp_profiles."""
    with conn.cursor() as cur:
        cur.execute(
            "SELECT segments FROM cdp_profiles WHERE tenant_id = %s AND profile_id = %s LIMIT 1",
            (tenant_id, profile_id),
        )
        row = cur.fetchone()
        if not row or not row["segments"]:
            return []
        raw = row["segments"]
        data = raw if isinstance(raw, list) else json.loads(raw)
        return [s.get("name") for s in data if isinstance(s, dict) and s.get("name")]


def _update_nba_columns(
    conn, tenant_id: str, profile_id: str, ticker: str,
    action: str, confidence: float, predicted_event: str, pred_prob: float,
) -> None:
    """Update the 4 NBA columns in product_recommendations."""
    with conn.cursor() as cur:
        cur.execute(_NBA_UPDATE_SQL, (
            action, confidence, predicted_event, pred_prob,
            tenant_id, profile_id, ticker,
            DUMMY_JOURNEY_MAP_ID, DUMMY_JOURNEY_STAGE_ID, DUMMY_REC_MODEL,
        ))
    conn.commit()


def _dispatch_channel(channel_key: str, profile_id: str, ticker: str, action: str, reason: str) -> None:
    """
    Dispatch via CHANNEL_REGISTRY. Imported lazily to avoid circular imports
    at module level in the lightweight Docker image.
    """
    try:
        from agentic_tools.marketing_tools import CHANNEL_REGISTRY
        channel_cls = CHANNEL_REGISTRY.get(channel_key)
        if channel_cls is None:
            logger.warning("Channel %s not in registry, skipping dispatch", channel_key)
            return
        # Instantiate and send a minimal notification
        channel_cls().send(
            recipient_segment=profile_id,
            message=f"[{action}] {reason} — ticker: {ticker}",
        )
        logger.info("Dispatched %s via %s for %s/%s", action, channel_key, profile_id, ticker)
    except Exception:
        logger.exception("Channel dispatch failed: %s for %s/%s", channel_key, profile_id, ticker)


def _post_webhook(payload: dict) -> None:
    """POST to external webhook if configured."""
    if not ACTIVATION_APP_WEBHOOK_URL:
        return
    try:
        requests.post(ACTIVATION_APP_WEBHOOK_URL, json=payload, timeout=5)
    except Exception:
        logger.exception("Webhook POST failed")


def _send_to_dlq(producer, raw_value: bytes, error: str) -> None:
    dlq_payload = {
        "original_topic": INPUT_TOPIC,
        "original_value": raw_value.decode("utf-8", errors="replace"),
        "error": str(error),
        "timestamp": datetime.datetime.now(datetime.timezone.utc).isoformat(),
    }
    producer.produce(topic=DLQ_TOPIC, value=json.dumps(dlq_payload).encode("utf-8"))
    producer.flush(timeout=5)


def _handle_signal(signum, frame):
    global _running
    logger.info("Received signal %d, shutting down...", signum)
    _running = False


def main():
    global _running
    signal.signal(signal.SIGTERM, _handle_signal)
    signal.signal(signal.SIGINT, _handle_signal)

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
    )

    start_http_server(8082)
    logger.info("Prometheus metrics server started on :8082")

    dry_run = not REALTIME_SCORING_ENABLED
    if dry_run:
        logger.warning("REALTIME_SCORING_ENABLED=False — dry-run mode")

    consumer = create_consumer(CONSUMER_GROUP, [INPUT_TOPIC], KAFKA_BOOTSTRAP_SERVERS)
    producer = create_producer(KAFKA_BOOTSTRAP_SERVERS)
    conn = psycopg.connect(_build_dsn(), row_factory=dict_row)

    logger.info("NBA publisher started. Group=%s Topic=%s", CONSUMER_GROUP, INPUT_TOPIC)

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
                with NBA_LATENCY.time():
                    score_msg = ScoreUpdateMessage.model_validate_json(raw_value)

                    # 1. Threshold check
                    if score_msg.score_delta <= SCORE_DELTA_THRESHOLD and score_msg.interest_score < INTEREST_SCORE_THRESHOLD:
                        logger.debug(
                            "Below threshold: delta=%.4f score=%.4f for %s/%s",
                            score_msg.score_delta, score_msg.interest_score,
                            score_msg.profile_id, score_msg.ticker,
                        )
                        break

                    # 2. Throttle check
                    if is_throttled(REDIS_URL, score_msg.profile_id, score_msg.ticker):
                        NBA_THROTTLED.inc()
                        logger.debug("Throttled: %s/%s", score_msg.profile_id, score_msg.ticker)
                        break

                    if dry_run:
                        logger.debug("[DRY-RUN] Would dispatch NBA for %s/%s", score_msg.profile_id, score_msg.ticker)
                        break

                    # 3. Fetch segments from PG
                    segments = _fetch_segments(conn, score_msg.tenant_id, score_msg.profile_id)

                    # 4. Predictive engine
                    predicted_event, pred_prob = predict_user_event(score_msg.interest_score, segments)

                    # 5. Prescriptive engine
                    action, channel, confidence, reason = recommend_system_action(
                        score_msg.interest_score, predicted_event
                    )

                    # 6. Channel dispatch
                    dispatch_keys = _CHANNEL_MAP.get(channel, [])
                    for ch_key in dispatch_keys:
                        _dispatch_channel(ch_key, score_msg.profile_id, score_msg.ticker, action, reason)
                        NBA_DISPATCHES.labels(channel=ch_key).inc()

                    # 7. Set throttle
                    set_throttle(REDIS_URL, score_msg.profile_id, score_msg.ticker)

                    # 8. Update NBA columns in PG
                    _update_nba_columns(
                        conn, score_msg.tenant_id, score_msg.profile_id, score_msg.ticker,
                        action, confidence, predicted_event, pred_prob,
                    )

                    # 9. Publish NbaActionMessage
                    nba_msg = NbaActionMessage(
                        tenant_id=score_msg.tenant_id,
                        profile_id=score_msg.profile_id,
                        ticker=score_msg.ticker,
                        action=action,
                        channel=channel,
                        confidence=confidence,
                        reason=reason,
                        dispatched_at=datetime.datetime.now(datetime.timezone.utc).isoformat(),
                    )
                    producer.produce(
                        topic=OUTPUT_TOPIC,
                        key=f"{score_msg.profile_id}:{score_msg.ticker}".encode("utf-8"),
                        value=nba_msg.model_dump_json().encode("utf-8"),
                    )
                    producer.flush(timeout=5)

                    # 10. Webhook
                    _post_webhook(nba_msg.model_dump())

                    logger.info(
                        "NBA dispatched: %s/%s action=%s channel=%s",
                        score_msg.profile_id, score_msg.ticker, action, channel,
                    )

                break  # success

            except Exception as e:
                retries += 1
                if retries > MAX_RETRIES:
                    logger.error("Max retries exceeded, sending to DLQ: %s", e)
                    _send_to_dlq(producer, raw_value, str(e))
                    break
                logger.warning("Retry %d/%d: %s", retries, MAX_RETRIES, e)
                time.sleep(0.5 * retries)

        consumer.commit(asynchronous=False)

    consumer.close()
    conn.close()
    logger.info("NBA publisher shut down.")


if __name__ == "__main__":
    main()
