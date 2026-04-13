"""
WebSocket Forwarder — Kafka → WebSocket bridge.

Reads scored CDC events from Kafka and reliably streams them over a persistent
WebSocket connection to an external team's server.  Designed for zero data loss:

  * Kafka auto-commit is DISABLED.
  * Each message is sent with a unique `event_id` (partition:offset).
  * The Kafka offset is committed ONLY after the WS server ACKs that event_id.
  * On WS disconnect the consumer pauses and reconnects with exponential backoff.
  * Malformed-payload errors from the server route the message to a DLQ so the
    consumer never gets permanently stuck.
"""

import asyncio
import json
import os
import signal
from datetime import datetime, timezone

import structlog
import websockets
from confluent_kafka import Consumer, Producer, KafkaError
from prometheus_client import Counter, Histogram, start_http_server

from services.ws_forwarder.config import (
    ACK_TIMEOUT_SECONDS,
    BACKOFF_BASE,
    BACKOFF_MAX,
    CONSUMER_GROUP,
    DLQ_TOPIC,
    INPUT_TOPIC,
    KAFKA_BOOTSTRAP_SERVERS,
    MAX_DLQ_RETRIES,
    MAX_SEND_RETRIES,
    WS_CLIENT_ID,
    WS_HANDSHAKE_TIMEOUT,
    WS_PING_INTERVAL,
    WS_PING_TIMEOUT,
    WS_URL,
)

logger = structlog.get_logger(__name__)

# ---------------------------------------------------------------------------
# Prometheus metrics
# ---------------------------------------------------------------------------
EVENTS_FORWARDED = Counter(
    "ws_forwarder_events_forwarded_total",
    "Messages successfully ACKed by the WS server",
)
EVENTS_DLQ = Counter(
    "ws_forwarder_events_dlq_total",
    "Messages routed to the dead-letter queue",
)
FORWARD_LATENCY = Histogram(
    "ws_forwarder_latency_seconds",
    "Send-to-ACK round-trip time",
)
WS_RECONNECTS = Counter(
    "ws_forwarder_reconnects_total",
    "Number of WebSocket reconnection attempts",
)

# ---------------------------------------------------------------------------
# Graceful shutdown flag
# ---------------------------------------------------------------------------
_shutdown_event = asyncio.Event()


def _install_signal_handlers(loop: asyncio.AbstractEventLoop) -> None:
    """Set _shutdown_event on SIGINT/SIGTERM so the main loop exits cleanly."""
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, _shutdown_event.set)


# ---------------------------------------------------------------------------
# PII Scrubbing placeholder
# ---------------------------------------------------------------------------
def scrub_pii(payload: dict) -> dict:
    """Strip or mask PII fields before forwarding.

    >>> # Example: remove hypothetical PII keys
    >>> # payload.pop("email", None)
    >>> # payload.pop("phone", None)

    Add your scrubbing rules here.  The function receives the deserialized
    Kafka value and must return the cleaned dict.
    """
    return payload


# ---------------------------------------------------------------------------
# Kafka helpers (sync — run in executor from async code)
# ---------------------------------------------------------------------------
def _create_consumer() -> Consumer:
    """Create a Kafka consumer with auto-commit DISABLED."""
    conf = {
        "bootstrap.servers": KAFKA_BOOTSTRAP_SERVERS,
        "group.id": CONSUMER_GROUP,
        "auto.offset.reset": "earliest",
        # CRITICAL: we commit manually after WS ACK
        "enable.auto.commit": False,
    }
    consumer = Consumer(conf)
    consumer.subscribe([INPUT_TOPIC])
    logger.info("kafka_consumer_created", group=CONSUMER_GROUP, topic=INPUT_TOPIC)
    return consumer


def _create_producer() -> Producer:
    conf = {
        "bootstrap.servers": KAFKA_BOOTSTRAP_SERVERS,
        "acks": "all",
        "enable.idempotence": True,
        "retries": 5,
        "compression.type": "lz4",
    }
    return Producer(conf)


def _send_to_dlq(producer: Producer, raw_value: bytes, error: str) -> None:
    """Route a permanently failed message to the DLQ topic."""
    dlq_payload = {
        "original_topic": INPUT_TOPIC,
        "original_value": raw_value.decode("utf-8", errors="replace"),
        "error": error,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }
    producer.produce(
        topic=DLQ_TOPIC,
        value=json.dumps(dlq_payload).encode("utf-8"),
    )
    producer.flush(timeout=5)
    EVENTS_DLQ.inc()
    logger.warning("message_sent_to_dlq", error=error)


# ---------------------------------------------------------------------------
# WebSocket connection manager
# ---------------------------------------------------------------------------
async def _connect_ws() -> websockets.ClientConnection:
    """Open a persistent WS connection, complete the auth handshake, and
    enable ping/pong keep-alive.

    Handshake protocol:
      1. Connect to the WS endpoint.
      2. Server sends an auth_request message.
      3. We respond with {"id": "<WS_CLIENT_ID>"}.
      4. Server sends {"status": "accepted"}.
    """
    ws = await websockets.connect(
        WS_URL,
        ping_interval=WS_PING_INTERVAL,
        ping_timeout=WS_PING_TIMEOUT,
        close_timeout=5,
    )
    logger.info("ws_tcp_connected", url=WS_URL)

    # --- Step 1: wait for auth_request from server ---
    raw = await asyncio.wait_for(ws.recv(), timeout=WS_HANDSHAKE_TIMEOUT)
    logger.info("ws_handshake_received", message=raw[:200] if isinstance(raw, str) else str(raw)[:200])

    # --- Step 2: send our client identity ---
    await ws.send(json.dumps({"id": WS_CLIENT_ID}))
    logger.info("ws_handshake_sent_id", client_id=WS_CLIENT_ID)

    # --- Step 3: wait for accepted ---
    raw = await asyncio.wait_for(ws.recv(), timeout=WS_HANDSHAKE_TIMEOUT)
    resp = json.loads(raw)
    if resp.get("status") != "accepted":
        await ws.close()
        raise ConnectionError(f"Handshake rejected: {resp}")

    logger.info("ws_handshake_accepted")
    return ws


async def _connect_with_backoff() -> websockets.ClientConnection:
    """Reconnect loop with capped exponential back-off."""
    attempt = 0
    while not _shutdown_event.is_set():
        try:
            ws = await _connect_ws()
            return ws
        except Exception as exc:
            attempt += 1
            delay = min(BACKOFF_BASE * (2 ** (attempt - 1)), BACKOFF_MAX)
            WS_RECONNECTS.inc()
            logger.warning("ws_connect_failed", attempt=attempt, error=str(exc), retry_in=delay)
            # Sleep interruptibly so we can shut down quickly
            try:
                await asyncio.wait_for(_shutdown_event.wait(), timeout=delay)
                # If we get here, shutdown was requested during the wait
                raise SystemExit("Shutdown requested during reconnect backoff")
            except asyncio.TimeoutError:
                # Timeout expired normally — continue retry loop
                pass


# ---------------------------------------------------------------------------
# Send-and-Wait: the core delivery loop for a single message
# ---------------------------------------------------------------------------
async def _send_and_wait_ack(
    ws: websockets.ClientConnection,
    event_id: str,
    payload: dict,
) -> dict:
    """Send a JSON envelope and wait for the server to ACK the event_id.

    Returns the parsed ACK response dict.
    Raises asyncio.TimeoutError if no ACK within ACK_TIMEOUT_SECONDS.
    Raises websockets.ConnectionClosed if the connection drops mid-flight.
    """
    envelope = {
        "event_id": event_id,
        "data": payload,
        "sent_at": datetime.now(timezone.utc).isoformat(),
    }
    logger.info("ws_sending", event_id=event_id, payload=payload)
    await ws.send(json.dumps(envelope))

    # Wait for the server's JSON response acknowledging *this* event_id.
    # The server may send other messages (heartbeats, etc.), so we loop
    # until we see our event_id or hit the timeout.
    deadline = asyncio.get_event_loop().time() + ACK_TIMEOUT_SECONDS
    while True:
        remaining = deadline - asyncio.get_event_loop().time()
        if remaining <= 0:
            raise asyncio.TimeoutError(f"No ACK for {event_id} within {ACK_TIMEOUT_SECONDS}s")

        raw_resp = await asyncio.wait_for(ws.recv(), timeout=remaining)
        try:
            resp = json.loads(raw_resp)
        except json.JSONDecodeError:
            logger.debug("ws_non_json_response", raw=raw_resp[:200])
            continue

        # The server acks sequentially without echoing event_id, so any
        # response carrying a `status` field is the ack for the most
        # recent send. Ignore heartbeats / server-pushed messages that
        # lack a status field.
        if "status" in resp:
            return resp


# ---------------------------------------------------------------------------
# Main async loop
# ---------------------------------------------------------------------------
async def _run() -> None:
    loop = asyncio.get_running_loop()
    _install_signal_handlers(loop)

    # Start Prometheus metrics server
    start_http_server(int(os.getenv("WS_FORWARDER_METRICS_PORT", "8082")))
    logger.info("prometheus_started", port=os.getenv("WS_FORWARDER_METRICS_PORT", "8082"))

    consumer = await loop.run_in_executor(None, _create_consumer)
    producer = await loop.run_in_executor(None, _create_producer)

    ws = await _connect_with_backoff()

    while not _shutdown_event.is_set():
        # ---------------------------------------------------------------
        # 1. Poll Kafka (non-blocking, run in executor to avoid blocking
        #    the async loop for too long)
        # ---------------------------------------------------------------
        msg = await loop.run_in_executor(None, lambda: consumer.poll(timeout=1.0))
        if msg is None:
            continue
        if msg.error():
            if msg.error().code() == KafkaError._PARTITION_EOF:
                continue
            logger.error("kafka_consumer_error", error=str(msg.error()))
            continue

        raw_value: bytes = msg.value()
        partition = msg.partition()
        offset = msg.offset()
        # Unique, deterministic event_id derived from Kafka coordinates
        event_id = f"{partition}:{offset}"

        # ---------------------------------------------------------------
        # 2. Deserialize & scrub PII
        # ---------------------------------------------------------------
        try:
            payload = json.loads(raw_value)
        except json.JSONDecodeError as exc:
            # Permanently malformed — route straight to DLQ, commit offset
            await loop.run_in_executor(
                None, _send_to_dlq, producer, raw_value, f"JSON decode error: {exc}",
            )
            await loop.run_in_executor(None, lambda: consumer.commit(asynchronous=False))
            continue

        payload = scrub_pii(payload)

        # ---------------------------------------------------------------
        # 3. Send-and-Wait with retries
        #    Offset is committed ONLY after a successful ACK.
        # ---------------------------------------------------------------
        send_attempts = 0
        committed = False

        while send_attempts < MAX_SEND_RETRIES and not _shutdown_event.is_set():
            send_attempts += 1
            try:
                with FORWARD_LATENCY.time():
                    resp = await _send_and_wait_ack(ws, event_id, payload)

                status = resp.get("status", "").lower()

                if status == "ok":
                    # --- Happy path: ACK received, safe to commit offset ---
                    await loop.run_in_executor(
                        None, lambda: consumer.commit(asynchronous=False),
                    )
                    committed = True
                    EVENTS_FORWARDED.inc()
                    logger.info("ack_received", event_id=event_id)
                    break

                elif status == "error" and resp.get("error_type") == "malformed_payload":
                    # --- Server says our payload is bad — DLQ, commit, move on ---
                    await loop.run_in_executor(
                        None,
                        _send_to_dlq,
                        producer,
                        raw_value,
                        f"Server rejected payload: {resp.get('message', '')}",
                    )
                    await loop.run_in_executor(
                        None, lambda: consumer.commit(asynchronous=False),
                    )
                    committed = True
                    break

                else:
                    # Unexpected status — treat as transient, retry
                    logger.warning("ws_unexpected_response", event_id=event_id, attempt=send_attempts, max=MAX_SEND_RETRIES, response=resp)

            except asyncio.TimeoutError:
                # No ACK within deadline — retry the same uncommitted message
                logger.warning("ack_timeout", event_id=event_id, attempt=send_attempts, max=MAX_SEND_RETRIES)

            except websockets.ConnectionClosed as exc:
                # Connection lost — pause consumption, reconnect, then retry
                logger.warning("ws_connection_lost", error=str(exc))
                ws = await _connect_with_backoff()
                # Do NOT commit — the message will be resent after reconnect

        # If we exhausted retries without committing, DLQ the message so the
        # consumer is not stuck forever on one bad message.
        if not committed and not _shutdown_event.is_set():
            logger.error("retries_exhausted_routing_to_dlq", event_id=event_id, max_retries=MAX_SEND_RETRIES)
            await loop.run_in_executor(
                None,
                _send_to_dlq,
                producer,
                raw_value,
                f"Exhausted {MAX_SEND_RETRIES} send retries",
            )
            await loop.run_in_executor(
                None, lambda: consumer.commit(asynchronous=False),
            )

    # -------------------------------------------------------------------
    # Graceful shutdown
    # -------------------------------------------------------------------
    logger.info("ws_forwarder_shutting_down")
    try:
        await ws.close()
    except Exception:
        pass
    consumer.close()
    logger.info("ws_forwarder_stopped")


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
            int(os.getenv("LOG_LEVEL", "20")),  # 20 = INFO
        ),
    )
    asyncio.run(_run())


if __name__ == "__main__":
    main()
