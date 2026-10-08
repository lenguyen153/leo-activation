"""Webhook Forwarder configuration — all values from environment."""

import os


KAFKA_BOOTSTRAP_SERVERS: str = os.getenv("KAFKA_BOOTSTRAP_SERVERS", "kafka:9092")

# Consumer group — distinct from ws-forwarder so both receive every message
CONSUMER_GROUP: str = "leo-webhook-forwarder-v1"
INPUT_TOPIC: str = os.getenv("WEBHOOK_FORWARDER_INPUT_TOPIC", "leo.score.updates")
DLQ_TOPIC: str = os.getenv("WEBHOOK_FORWARDER_DLQ_TOPIC", "leo.webhook-forwarder.dlq")

# Destination HTTP webhook
WEBHOOK_URL: str = os.getenv(
    "WEBHOOK_FORWARDER_URL",
    "http://118.69.83.26:8006/api/v1/webhook/cdp",
)
HTTP_TIMEOUT_SECONDS: float = float(os.getenv("WEBHOOK_HTTP_TIMEOUT", "5"))

# Exponential back-off for 5xx / network errors (retried until success)
BACKOFF_BASE: float = 1.0   # seconds
BACKOFF_MAX: float = 60.0   # cap

# Event ID prefix — same format as ws-forwarder: "<env>-<partition>:<offset>"
EVENT_ID_ENV: str = os.getenv("WEBHOOK_FORWARDER_ENV", os.getenv("WS_FORWARDER_ENV", ""))
