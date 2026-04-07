"""Scoring Consumer configuration — all values from environment."""

import os


REDIS_URL: str = os.getenv("REDIS_URL", "redis://localhost:6379/2")
KAFKA_BOOTSTRAP_SERVERS: str = os.getenv("KAFKA_BOOTSTRAP_SERVERS", "kafka:9092")

# PostgreSQL — reuse the same env vars as the main app (DatabaseSettings)
PGSQL_DB_HOST: str = os.getenv("PGSQL_DB_HOST", "localhost")
PGSQL_DB_PORT: int = int(os.getenv("PGSQL_DB_PORT", "5435"))
PGSQL_DB_NAME: str = os.getenv("PGSQL_DB_NAME", "leo_cdp")
PGSQL_DB_USER: str = os.getenv("PGSQL_DB_USER", "postgres")
PGSQL_DB_PASSWORD: str = os.getenv("PGSQL_DB_PASSWORD", "")

# Consumer group
CONSUMER_GROUP: str = "leo-scoring-v1"
INPUT_TOPIC: str = "cdp.events.raw"
OUTPUT_TOPIC: str = "leo.score.updates"
DLQ_TOPIC: str = "leo.dlq"

MAX_RETRIES: int = 3

REALTIME_SCORING_ENABLED: bool = os.getenv("REALTIME_SCORING_ENABLED", "False").lower() in ("1", "true", "yes")

# External API forwarding (empty = disabled)
EVENT_FORWARD_URL: str = os.getenv("EVENT_FORWARD_URL", "")
