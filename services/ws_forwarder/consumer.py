"""
WebSocket Forwarder — Kafka → WebSocket bridge + inbound command handler.

Reads scored CDC events from Kafka and reliably streams them over a persistent
WebSocket connection to an external team's server.  Designed for zero data loss:

  * Kafka auto-commit is DISABLED.
  * Each message is sent with a unique `event_id` (partition:offset).
  * The Kafka offset is committed ONLY after the WS server ACKs that event_id.
  * On WS disconnect the consumer pauses and reconnects with exponential backoff.
  * Malformed-payload errors from the server route the message to a DLQ so the
    consumer never gets permanently stuck.

Inbound command handling (server → us):
  * {"action": "start_learning", "user_id": "<base_account_id>"}
    → resolves profile_id via PG, streams all ArangoDB events back to the server
  * {"action": "stop_learning", "user_id": "<base_account_id>"}
    → cancels the active stream for that user

All outbound sends are serialised through a shared asyncio.Lock so that the
Kafka-forwarding loop and learning streams never interleave at the socket level.
"""

import asyncio
import json
import logging
import os
import signal
from datetime import datetime, timezone
from typing import Optional

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
    WS_FORWARDER_ENV,
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
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, _shutdown_event.set)


# ---------------------------------------------------------------------------
# PII Scrubbing
# ---------------------------------------------------------------------------
def scrub_pii(payload: dict) -> dict:
    return {
        "base_account_id": payload.get("base_account_id"),
        "ticker": payload.get("ticker"),
        "metric_name": payload.get("metric_name"),
        "journey_id": payload.get("journey_id"),
        "event_payload": payload.get("event_data", {}),
        "updated_at": payload.get("updated_at"),
    }


# ---------------------------------------------------------------------------
# Kafka helpers
# ---------------------------------------------------------------------------
def _create_consumer() -> Consumer:
    conf = {
        "bootstrap.servers": KAFKA_BOOTSTRAP_SERVERS,
        "group.id": CONSUMER_GROUP,
        "auto.offset.reset": "earliest",
        "enable.auto.commit": False,
    }
    consumer = Consumer(conf)
    consumer.subscribe([INPUT_TOPIC])
    logger.info("kafka_consumer_created", group=CONSUMER_GROUP, topic=INPUT_TOPIC)
    return consumer


def _create_producer() -> Producer:
    conf = {
        "bootstrap.servers": KAFKA_BOOTSTRAP_SERVERS,
        "acks": 1,
        "retries": 3,
        "compression.type": "lz4",
    }
    return Producer(conf)


def _send_to_dlq(producer: Producer, raw_value: bytes, error: str) -> None:
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
    ws = await websockets.connect(
        WS_URL,
        ping_interval=WS_PING_INTERVAL,
        ping_timeout=WS_PING_TIMEOUT,
        close_timeout=5,
    )
    logger.info("ws_tcp_connected", url=WS_URL)

    raw = await asyncio.wait_for(ws.recv(), timeout=WS_HANDSHAKE_TIMEOUT)
    logger.info("ws_handshake_received", message=raw[:200] if isinstance(raw, str) else str(raw)[:200])

    await ws.send(json.dumps({"id": WS_CLIENT_ID}))
    logger.info("ws_handshake_sent_id", client_id=WS_CLIENT_ID)

    raw = await asyncio.wait_for(ws.recv(), timeout=WS_HANDSHAKE_TIMEOUT)
    resp = json.loads(raw)
    if resp.get("status") != "accepted":
        await ws.close()
        raise ConnectionError(f"Handshake rejected: {resp}")

    logger.info("ws_handshake_accepted")
    return ws


async def _connect_with_backoff() -> websockets.ClientConnection:
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
            try:
                await asyncio.wait_for(_shutdown_event.wait(), timeout=delay)
                raise SystemExit("Shutdown requested during reconnect backoff")
            except asyncio.TimeoutError:
                pass


# ---------------------------------------------------------------------------
# Inbound message demultiplexer
# ---------------------------------------------------------------------------
async def _ws_receiver(
    ws: websockets.ClientConnection,
    ack_queue: asyncio.Queue,
    cmd_queue: asyncio.Queue,
) -> None:
    """
    Continuously reads from the WS connection and routes messages:
      - {"status": ...}  → ack_queue   (Kafka forwarding ACKs)
      - {"action": ...}  → cmd_queue   (start_learning / stop_learning)
    Exits when the connection closes.
    """
    while not _shutdown_event.is_set():
        try:
            raw = await ws.recv()
        except websockets.ConnectionClosed:
            break
        try:
            msg = json.loads(raw)
        except json.JSONDecodeError:
            logger.debug("ws_non_json_inbound", raw=str(raw)[:200])
            continue

        if "status" in msg:
            await ack_queue.put(msg)
        elif "action" in msg:
            logger.info("ws_command_received", action=msg.get("action"), user_id=msg.get("user_id"))
            await cmd_queue.put(msg)
        else:
            logger.warning("ws_unroutable_message", msg=str(msg)[:200])


# ---------------------------------------------------------------------------
# Learning — DB helpers (sync, run in executor)
# ---------------------------------------------------------------------------
_AQL_ALL_EVENTS = """
FOR event IN cdp_trackingevent
    FILTER event.refProfileId == @profile_id OR event.fingerprintId == @profile_id
    FILTER event.createdAt >= @start_time AND event.createdAt <= @stop_time
    SORT event.createdAt ASC
    RETURN {
        metricName: event.metricName,
        eventData: event.eventData,
        createdAt: event.createdAt
    }
"""


def _resolve_profile_id(base_account_id: str) -> Optional[str]:
    from data_utils.settings import DatabaseSettings
    settings = DatabaseSettings()
    conn = settings.get_pg_connection()
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT profile_id FROM cdp_profiles WHERE ext_data->>'base_account_id' = %s LIMIT 1",
                (base_account_id.strip(),),
            )
            row = cur.fetchone()
            if not row:
                return None
            return row["profile_id"] if isinstance(row, dict) else row[0]
    finally:
        conn.close()


def _fetch_all_events(profile_id: str, start_time: str, stop_time: str) -> list:
    from data_utils.settings import DatabaseSettings
    settings = DatabaseSettings()
    db = settings.get_arango_db()
    cursor = db.aql.execute(
        _AQL_ALL_EVENTS,
        bind_vars={"profile_id": profile_id, "start_time": start_time, "stop_time": stop_time},
        batch_size=500,
    )
    return list(cursor)


async def _fetch_and_send_learning_data(
    user_id: str,
    start_time: str,
    stop_time: str,
    ws: websockets.ClientConnection,
    send_lock: asyncio.Lock,
) -> None:
    """Resolves profile, fetches all events, sends one bulk payload."""
    loop = asyncio.get_event_loop()

    profile_id = await loop.run_in_executor(None, _resolve_profile_id, user_id)
    if not profile_id:
        logger.warning("learning_no_profile", user_id=user_id)
        async with send_lock:
            await ws.send(json.dumps({
                "action": "error",
                "user_id": user_id,
                "message": f"No profile found for user_id '{user_id}'",
            }))
        return

    logger.info("learning_fetching_events", user_id=user_id, profile_id=profile_id)
    try:
        events = await loop.run_in_executor(None, _fetch_all_events, profile_id, start_time, stop_time)
    except Exception as exc:
        logger.error("learning_fetch_failed", user_id=user_id, error=str(exc))
        async with send_lock:
            await ws.send(json.dumps({
                "action": "error",
                "user_id": user_id,
                "message": f"Failed to fetch events: {exc}",
            }))
        return

    logger.info("learning_sending_data", user_id=user_id, total_events=len(events))
    async with send_lock:
        await ws.send(json.dumps({
            "action": "learning_data",
            "user_id": user_id,
            "start_time": start_time,
            "stop_time": stop_time,
            "total_events": len(events),
            "events": events,
        }, default=str))

    logger.info("learning_data_sent", user_id=user_id, total_events=len(events))


# ---------------------------------------------------------------------------
# Command handler
# ---------------------------------------------------------------------------
async def _command_handler(
    cmd_queue: asyncio.Queue,
    learning_user_ids: set,
    ws: websockets.ClientConnection,
    send_lock: asyncio.Lock,
) -> None:
    """
    start_learning → records start_time, tags live Kafka events with mode=learning.
    stop_learning  → fetches all ArangoDB events and sends them in one bulk payload.
    """
    sessions: dict[str, str] = {}  # user_id → start_time ISO string

    while not _shutdown_event.is_set():
        try:
            cmd = await asyncio.wait_for(cmd_queue.get(), timeout=1.0)
        except asyncio.TimeoutError:
            continue

        action = cmd.get("action", "").strip()
        user_id = cmd.get("user_id", "").strip()

        if not user_id:
            logger.warning("ws_command_missing_user_id", action=action)
            continue

        if action == "start_learning":
            if user_id in sessions:
                logger.warning("learning_already_active", user_id=user_id)
                continue
            start_time = datetime.now(timezone.utc).isoformat()
            sessions[user_id] = start_time
            learning_user_ids.add(user_id)
            logger.info("learning_started", user_id=user_id, start_time=start_time)

        elif action == "stop_learning":
            if user_id not in sessions:
                logger.warning("learning_not_active", user_id=user_id)
                continue
            start_time = sessions.pop(user_id)
            learning_user_ids.discard(user_id)
            stop_time = datetime.now(timezone.utc).isoformat()
            logger.info("learning_stop_received", user_id=user_id, start_time=start_time, stop_time=stop_time)
            asyncio.create_task(
                _fetch_and_send_learning_data(user_id, start_time, stop_time, ws, send_lock)
            )

        else:
            logger.warning("ws_unknown_command", action=action)


# ---------------------------------------------------------------------------
# Send-and-Wait: Kafka event delivery
# ---------------------------------------------------------------------------
async def _send_and_wait_ack(
    ws: websockets.ClientConnection,
    send_lock: asyncio.Lock,
    ack_queue: asyncio.Queue,
    event_id: str,
    payload: dict,
) -> dict:
    """
    Send a Kafka event envelope and wait for the server's ACK from ack_queue.
    Uses send_lock to avoid interleaving with learning-stream sends.
    """
    envelope = {
        "event_id": event_id,
        "data": payload,
        "sent_at": datetime.now(timezone.utc).isoformat(),
    }
    logger.info("ws_sending", event_id=event_id, payload=payload)
    async with send_lock:
        await ws.send(json.dumps(envelope))

    deadline = asyncio.get_event_loop().time() + ACK_TIMEOUT_SECONDS
    while True:
        remaining = deadline - asyncio.get_event_loop().time()
        if remaining <= 0:
            raise asyncio.TimeoutError(f"No ACK for {event_id} within {ACK_TIMEOUT_SECONDS}s")
        try:
            resp = await asyncio.wait_for(ack_queue.get(), timeout=remaining)
        except asyncio.TimeoutError:
            raise asyncio.TimeoutError(f"No ACK for {event_id} within {ACK_TIMEOUT_SECONDS}s")
        if "status" in resp:
            return resp


# ---------------------------------------------------------------------------
# Main async loop
# ---------------------------------------------------------------------------
async def _run() -> None:
    loop = asyncio.get_running_loop()
    _install_signal_handlers(loop)

    start_http_server(int(os.getenv("WS_FORWARDER_METRICS_PORT", "8082")))
    logger.info("prometheus_started", port=os.getenv("WS_FORWARDER_METRICS_PORT", "8082"))

    consumer = await loop.run_in_executor(None, _create_consumer)
    producer = await loop.run_in_executor(None, _create_producer)

    ws = await _connect_with_backoff()

    send_lock = asyncio.Lock()
    ack_queue: asyncio.Queue = asyncio.Queue()
    cmd_queue: asyncio.Queue = asyncio.Queue()
    learning_user_ids: set = set()

    receiver_task = asyncio.create_task(_ws_receiver(ws, ack_queue, cmd_queue))
    command_task = asyncio.create_task(_command_handler(cmd_queue, learning_user_ids, ws, send_lock))

    while not _shutdown_event.is_set():
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
        event_id = f"{WS_FORWARDER_ENV}-{partition}:{offset}" if WS_FORWARDER_ENV else f"{partition}:{offset}"

        try:
            payload = json.loads(raw_value)
        except json.JSONDecodeError as exc:
            await loop.run_in_executor(
                None, _send_to_dlq, producer, raw_value, f"JSON decode error: {exc}",
            )
            await loop.run_in_executor(None, lambda: consumer.commit(asynchronous=False))
            continue

        payload = scrub_pii(payload)

        if payload.get("base_account_id") in learning_user_ids:
            payload["mode"] = "learning"

        send_attempts = 0
        committed = False

        while send_attempts < MAX_SEND_RETRIES and not _shutdown_event.is_set():
            send_attempts += 1
            try:
                with FORWARD_LATENCY.time():
                    resp = await _send_and_wait_ack(ws, send_lock, ack_queue, event_id, payload)

                status = resp.get("status", "").lower()

                if status == "ok":
                    await loop.run_in_executor(
                        None, lambda: consumer.commit(asynchronous=False),
                    )
                    committed = True
                    EVENTS_FORWARDED.inc()
                    logger.info("ack_received", event_id=event_id)
                    break

                elif status == "error" and resp.get("error_type") == "malformed_payload":
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
                    logger.warning("ws_unexpected_response", event_id=event_id, attempt=send_attempts, response=resp)

            except asyncio.TimeoutError:
                logger.warning("ack_timeout", event_id=event_id, attempt=send_attempts, max=MAX_SEND_RETRIES)

            except websockets.ConnectionClosed as exc:
                logger.warning("ws_connection_lost", error=str(exc))
                receiver_task.cancel()
                command_task.cancel()
                ws = await _connect_with_backoff()
                send_lock = asyncio.Lock()
                ack_queue = asyncio.Queue()
                cmd_queue = asyncio.Queue()
                receiver_task = asyncio.create_task(_ws_receiver(ws, ack_queue, cmd_queue))
                command_task = asyncio.create_task(_command_handler(cmd_queue, learning_user_ids, ws, send_lock))

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
    receiver_task.cancel()
    command_task.cancel()
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
            int(os.getenv("LOG_LEVEL", "20")),
        ),
    )
    asyncio.run(_run())


if __name__ == "__main__":
    main()
