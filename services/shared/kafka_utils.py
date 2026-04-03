"""Kafka producer/consumer factory helpers."""

import logging
import os

from confluent_kafka import Producer, Consumer

logger = logging.getLogger(__name__)


def create_producer(bootstrap_servers: str | None = None) -> Producer:
    """Create an idempotent Kafka producer with acks=all."""
    servers = bootstrap_servers or os.getenv("KAFKA_BOOTSTRAP_SERVERS", "kafka:9092")
    conf = {
        "bootstrap.servers": servers,
        "acks": "all",
        "enable.idempotence": True,
        "max.in.flight.requests.per.connection": 5,
        "retries": 5,
        "linger.ms": 10,
        "compression.type": "lz4",
    }
    logger.info("Creating Kafka producer: %s", servers)
    return Producer(conf)


def create_consumer(
    group_id: str,
    topics: list[str],
    bootstrap_servers: str | None = None,
    extra_conf: dict | None = None,
) -> Consumer:
    """Create a Kafka consumer with earliest offset reset."""
    servers = bootstrap_servers or os.getenv("KAFKA_BOOTSTRAP_SERVERS", "kafka:9092")
    conf = {
        "bootstrap.servers": servers,
        "group.id": group_id,
        "auto.offset.reset": "earliest",
        "enable.auto.commit": False,
    }
    if extra_conf:
        conf.update(extra_conf)
    logger.info("Creating Kafka consumer group=%s topics=%s", group_id, topics)
    consumer = Consumer(conf)
    consumer.subscribe(topics)
    return consumer
