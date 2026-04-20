"""
CDC Poller — main loop.

Reads ArangoDB WAL via logger-follow, filters + transforms events,
publishes to Kafka topic `cdp.events.raw`, and advances tick checkpoint.

Leader election via Redis SETNX to prevent duplicate pollers.
"""

import json
import logging
import signal
import sys
import time

import redis
import requests
from prometheus_client import Counter, Histogram, Gauge, start_http_server

from services.cdc_poller.config import (
    ARANGO_USER,
    ARANGO_PASSWORD,
    BATCH_LIMIT,
    CDC_TOPIC,
    KAFKA_BOOTSTRAP_SERVERS,
    POLL_INTERVAL_S,
    REALTIME_SCORING_ENABLED,
    REDIS_URL,
    WAL_CHUNK_SIZE,
    get_arango_replication_base_url,
)
from services.cdc_poller.filters import should_publish
from services.cdc_poller.metric_cache import start_background_refresh
from services.cdc_poller.tick_store import bootstrap_tick, get_tick, set_tick
from services.cdc_poller.transformer import transform
from services.shared.kafka_utils import create_producer

logger = logging.getLogger(__name__)

# --- Prometheus Metrics ---
EVENTS_PUBLISHED = Counter("cdc_events_published_total", "Total CDC events published to Kafka")
POLL_LATENCY = Histogram("cdc_poll_latency_seconds", "Latency of each WAL poll cycle")
TICK_LAG = Gauge("cdc_tick_lag", "Difference between WAL head and processed tick")

# --- Leader Election ---
LEADER_KEY = "cdc:poller:leader"
LEADER_TTL_S = 30

_running = True


def _acquire_leadership(r: redis.Redis) -> bool:
    """Try to acquire leader lock via Redis SETNX."""
    acquired = r.set(LEADER_KEY, "1", nx=True, ex=LEADER_TTL_S)
    return bool(acquired)


def _renew_leadership(r: redis.Redis) -> bool:
    """Renew leader lock TTL."""
    return bool(r.expire(LEADER_KEY, LEADER_TTL_S))


def _poll_wal(tick: int) -> tuple[list[dict], int]:
    """
    HTTP GET to ArangoDB WAL logger-follow.
    Returns (entries, last_tick_in_response).
    """
    base = get_arango_replication_base_url()
    url = (
        f"{base}/_api/replication/logger-follow"
        f"?from={tick}&chunkSize={WAL_CHUNK_SIZE}"
    )
    resp = requests.get(url, auth=(ARANGO_USER, ARANGO_PASSWORD), timeout=30)

    if resp.status_code == 204:
        # No new data
        return [], tick

    resp.raise_for_status()

    entries = []
    for line in resp.text.strip().split("\n"):
        line = line.strip()
        if not line:
            continue
        try:
            entries.append(json.loads(line))
        except json.JSONDecodeError:
            logger.warning("Skipping malformed WAL line: %.80s", line)

    # The response header x-arango-replication-lastincluded gives the last tick
    last_included = resp.headers.get("x-arango-replication-lastincluded", str(tick))
    return entries, int(last_included)


def _flush_to_kafka(producer, messages, dry_run: bool) -> int:
    """Produce messages to Kafka. Returns count published."""
    if not messages:
        return 0

    count = 0
    for msg in messages:
        if dry_run:
            logger.info("[DRY-RUN] Would publish: %s/%s", msg.fingerprint_id, msg.ticker)
            count += 1
            continue

        producer.produce(
            topic=CDC_TOPIC,
            key=msg.ticker.encode("utf-8"),
            value=msg.model_dump_json().encode("utf-8"),
        )
        count += 1

    if not dry_run:
        producer.flush(timeout=10)

    EVENTS_PUBLISHED.inc(count)
    return count


def _handle_signal(signum, frame):
    global _running
    logger.info("Received signal %d, shutting down gracefully...", signum)
    _running = False


def main():
    global _running
    signal.signal(signal.SIGTERM, _handle_signal)
    signal.signal(signal.SIGINT, _handle_signal)

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
    )

    # Start Prometheus metrics server
    start_http_server(8080)
    logger.info("Prometheus metrics server started on :8080")

    r = redis.from_url(REDIS_URL, decode_responses=True)
    dry_run = not REALTIME_SCORING_ENABLED

    if dry_run:
        logger.warning("REALTIME_SCORING_ENABLED=False — running in dry-run mode (consume but don't write)")

    # Leader election loop
    while _running:
        if not _acquire_leadership(r):
            logger.info("Another poller is leader. Retrying in %ds...", LEADER_TTL_S)
            time.sleep(LEADER_TTL_S)
            continue

        logger.info("Acquired leadership. Starting CDC poll loop.")
        break

    # Bootstrap
    tick = bootstrap_tick()
    logger.info("Starting from tick: %d", tick)

    # Start metric cache background refresh
    start_background_refresh()

    # Create Kafka producer
    producer = create_producer(KAFKA_BOOTSTRAP_SERVERS)

    while _running:
        with POLL_LATENCY.time():
            try:
                _renew_leadership(r)

                entries, last_tick = _poll_wal(tick)

                if not entries:
                    time.sleep(POLL_INTERVAL_S)
                    continue

                # Filter + transform — track the tick of the last processed entry
                all_messages = []
                processed_tick = tick

                # Diagnostic: count entries by collection
                from collections import Counter as _Counter
                cname_counts = _Counter(e.get("cname", "<none>") for e in entries if e.get("type") == 2300)
                type_counts = _Counter(e.get("type") for e in entries)
                logger.info(
                    "[WAL batch] %d entries total | types=%s | doc-collections=%s",
                    len(entries), dict(type_counts), dict(cname_counts),
                )

                for entry in entries:
                    entry_tick = int(entry.get("tick", last_tick))

                    if entry.get("type") == 2300 and entry.get("cname") == "cdp_trackingevent":
                        data = entry.get("data", {})
                        metric = data.get("metricName")
                        event_data = data.get("eventData", {})
                        has_single = bool(event_data.get("instrument_id"))
                        has_list = isinstance(event_data.get("instrument_id_list"), list) and len(event_data["instrument_id_list"]) > 0
                        from services.cdc_poller.filters import CDC_METRIC_NAMES
                        if metric not in CDC_METRIC_NAMES:
                            logger.debug("[WAL skip] metricName=%r not whitelisted (tick=%d)", metric, entry_tick)
                        elif not (has_single or has_list):
                            logger.warning(
                                "[WAL skip] metricName=%r has no instrument_id/instrument_id_list | eventData=%s (tick=%d)",
                                metric, event_data, entry_tick,
                            )
                        else:
                            logger.info("[WAL match] metricName=%r instrument_id=%r (tick=%d)", metric, event_data.get("instrument_id"), entry_tick)

                    if should_publish(entry):
                        all_messages.extend(transform(entry))
                    processed_tick = entry_tick

                    # Respect batch limit
                    if len(all_messages) >= BATCH_LIMIT:
                        break

                # Flush to Kafka
                published = _flush_to_kafka(producer, all_messages, dry_run=dry_run)

                # Advance tick ONLY after successful flush
                # Use processed_tick (last entry we actually saw), not last_tick
                # from HTTP header, to avoid skipping entries on batch-limit break
                set_tick(processed_tick)
                tick = processed_tick

                TICK_LAG.set(0)  # Will be updated properly when we can compare to WAL head

                if published:
                    mode = "[DRY-RUN] Detected" if dry_run else "Published"
                    logger.info("%s %d events, tick advanced to %d", mode, published, tick)

            except requests.exceptions.RequestException as e:
                logger.error("WAL poll failed: %s", e)
                time.sleep(POLL_INTERVAL_S * 2)
            except Exception:
                logger.exception("Unexpected error in poll loop")
                time.sleep(POLL_INTERVAL_S * 2)

        time.sleep(POLL_INTERVAL_S)

    logger.info("CDC Poller shut down.")


if __name__ == "__main__":
    main()
