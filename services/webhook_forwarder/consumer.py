"""
Webhook Forwarder — Kafka → HTTP webhook bridge.

Runs alongside the WS forwarder and POSTs the same scored CDC events (same
envelope) to the other team's HTTP webhook:

  * Kafka auto-commit is DISABLED.
  * Each message is sent with a unique `event_id` (partition:offset).
  * The Kafka offset is committed ONLY after the webhook returns HTTP 200.
  * 5xx / timeouts / connection errors retry with capped exponential backoff
    until success (the consumer pauses, nothing is lost).
  * 4xx (payload rejected) routes the message to a DLQ so the consumer never
    gets permanently stuck.
"""

import json
import logging
import os
import signal
import threading
from datetime import datetime, timezone

import httpx
import structlog
from confluent_kafka import Consumer, KafkaError, Producer
from prometheus_client import Counter, Histogram, start_http_server

from services.webhook_forwarder.config import (
    BACKOFF_BASE,
    BACKOFF_MAX,
    CONSUMER_GROUP,
    DLQ_TOPIC,
    EVENT_ID_ENV,
    HTTP_TIMEOUT_SECONDS,
    INPUT_TOPIC,
    KAFKA_BOOTSTRAP_SERVERS,
    WEBHOOK_URL,
)
from services.ws_forwarder.consumer import scrub_pii

logger = structlog.get_logger(__name__)

# ---------------------------------------------------------------------------
# Prometheus metrics
# ---------------------------------------------------------------------------
EVENTS_FORWARDED = Counter(
    "webhook_forwarder_events_forwarded_total",
    "Messages accepted (HTTP 200) by the webhook",
)
EVENTS_DLQ = Counter(
    "webhook_forwarder_events_dlq_total",
    "Messages routed to the dead-letter queue",
)
SEND_RETRIES = Counter(
    "webhook_forwarder_send_retries_total",
    "Retried sends after 5xx / network errors",
)
FORWARD_LATENCY = Histogram(
    "webhook_forwarder_latency_seconds",
    "HTTP POST round-trip time",
)

# ---------------------------------------------------------------------------
# Graceful shutdown flag
# ---------------------------------------------------------------------------
_shutdown_event = threading.Event()


def _install_signal_handlers() -> None:
    for sig in (signal.SIGINT, signal.SIGTERM):
        signal.signal(sig, lambda *_: _shutdown_event.set())


# ---------------------------------------------------------------------------
# Kafka helpers
# ---------------------------------------------------------------------------
def _create_consumer() -> Consumer:
    consumer = Consumer({
        "bootstrap.servers": KAFKA_BOOTSTRAP_SERVERS,
        "group.id": CONSUMER_GROUP,
        "auto.offset.reset": "earliest",
        "enable.auto.commit": False,
    })
    consumer.subscribe([INPUT_TOPIC])
    logger.info("kafka_consumer_created", group=CONSUMER_GROUP, topic=INPUT_TOPIC)
    return consumer


def _create_producer() -> Producer:
    return Producer({
        "bootstrap.servers": KAFKA_BOOTSTRAP_SERVERS,
        "acks": 1,
        "retries": 3,
        "compression.type": "lz4",
    })


def _send_to_dlq(producer: Producer, raw_value: bytes, error: str) -> None:
    dlq_payload = {
        "original_topic": INPUT_TOPIC,
        "original_value": raw_value.decode("utf-8", errors="replace"),
        "error": error,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }
    producer.produce(topic=DLQ_TOPIC, value=json.dumps(dlq_payload).encode("utf-8"))
    producer.flush(timeout=5)
    EVENTS_DLQ.inc()
    logger.warning("message_sent_to_dlq", error=error)


# ---------------------------------------------------------------------------
# HTTP delivery
# ---------------------------------------------------------------------------
def build_envelope(event_id: str, payload: dict) -> dict:
    return {
        "event_id": event_id,
        "data": payload,
        "sent_at": datetime.now(timezone.utc).isoformat(),
    }


DELIVERED = "delivered"
REJECTED = "rejected"
ABORTED = "aborted"


def deliver(client: httpx.Client, event_id: str, payload: dict) -> tuple[str, str]:
    """
    POST the event until it is either accepted or permanently rejected.

    Returns (status, error):
      * (DELIVERED, "")  — HTTP 200
      * (REJECTED, msg)  — HTTP 4xx, message should go to the DLQ
      * (ABORTED, "")    — shutdown requested while retrying; do not commit
    5xx / network errors are retried forever with capped backoff.
    """
    attempt = 0
    while not _shutdown_event.is_set():
        envelope = build_envelope(event_id, payload)
        try:
            with FORWARD_LATENCY.time():
                resp = client.post(WEBHOOK_URL, json=envelope)
            if resp.status_code == 200:
                return DELIVERED, ""
            if 400 <= resp.status_code < 500:
                return REJECTED, f"Webhook rejected payload: HTTP {resp.status_code} {resp.text[:500]}"
            error = f"HTTP {resp.status_code} {resp.text[:200]}"
        except httpx.HTTPError as exc:
            error = f"{type(exc).__name__}: {exc}"

        attempt += 1
        delay = min(BACKOFF_BASE * (2 ** (attempt - 1)), BACKOFF_MAX)
        SEND_RETRIES.inc()
        logger.warning("webhook_send_failed", event_id=event_id, attempt=attempt, error=error, retry_in=delay)
        _shutdown_event.wait(delay)
    return ABORTED, ""


# ---------------------------------------------------------------------------
# Main loop
# ---------------------------------------------------------------------------
def _run() -> None:
    _install_signal_handlers()

    port = int(os.getenv("WEBHOOK_FORWARDER_METRICS_PORT", "8083"))
    start_http_server(port)
    logger.info("prometheus_started", port=port)

    consumer = _create_consumer()
    producer = _create_producer()
    client = httpx.Client(timeout=HTTP_TIMEOUT_SECONDS)

    while not _shutdown_event.is_set():
        msg = consumer.poll(timeout=1.0)
        if msg is None:
            continue
        if msg.error():
            if msg.error().code() != KafkaError._PARTITION_EOF:
                logger.error("kafka_consumer_error", error=str(msg.error()))
            continue

        raw_value: bytes = msg.value()
        partition, offset = msg.partition(), msg.offset()
        event_id = f"{EVENT_ID_ENV}-{partition}:{offset}" if EVENT_ID_ENV else f"{partition}:{offset}"

        try:
            payload = scrub_pii(json.loads(raw_value))
        except json.JSONDecodeError as exc:
            _send_to_dlq(producer, raw_value, f"JSON decode error: {exc}")
            consumer.commit(asynchronous=False)
            continue

        logger.info("webhook_sending", event_id=event_id, payload=payload)
        status, error = deliver(client, event_id, payload)

        if status == ABORTED:
            break  # uncommitted — redelivered on restart
        if status == REJECTED:
            _send_to_dlq(producer, raw_value, error)
        else:
            EVENTS_FORWARDED.inc()
            logger.info("webhook_delivered", event_id=event_id)
        consumer.commit(asynchronous=False)

    logger.info("webhook_forwarder_shutting_down")
    client.close()
    consumer.close()
    logger.info("webhook_forwarder_stopped")


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------
def main() -> None:
    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="iso"),
            structlog.dev.ConsoleRenderer()
            if os.getenv("LOG_FORMAT", "json") != "json"
            else structlog.processors.JSONRenderer(),
        ],
        wrapper_class=structlog.make_filtering_bound_logger(
            int(os.getenv("LOG_LEVEL", "20")),
        ),
    )
    _run()


if __name__ == "__main__":
    main()
