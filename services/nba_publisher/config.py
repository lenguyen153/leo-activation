"""NBA Publisher configuration — all values from environment."""

import os


REDIS_URL: str = os.getenv("REDIS_URL", "redis://localhost:6379/2")
KAFKA_BOOTSTRAP_SERVERS: str = os.getenv("KAFKA_BOOTSTRAP_SERVERS", "kafka:9092")

# PostgreSQL
PGSQL_DB_HOST: str = os.getenv("PGSQL_DB_HOST", "localhost")
PGSQL_DB_PORT: int = int(os.getenv("PGSQL_DB_PORT", "5435"))
PGSQL_DB_NAME: str = os.getenv("PGSQL_DB_NAME", "leo_cdp")
PGSQL_DB_USER: str = os.getenv("PGSQL_DB_USER", "postgres")
PGSQL_DB_PASSWORD: str = os.getenv("PGSQL_DB_PASSWORD", "")

# Consumer group
CONSUMER_GROUP: str = "leo-nba-v1"
INPUT_TOPIC: str = "leo.score.updates"
OUTPUT_TOPIC: str = "leo.nba.actions"
DLQ_TOPIC: str = "leo.dlq"

MAX_RETRIES: int = 3

# Thresholds for triggering NBA dispatch
SCORE_DELTA_THRESHOLD: float = float(os.getenv("NBA_SCORE_DELTA_THRESHOLD", "0.1"))
INTEREST_SCORE_THRESHOLD: float = float(os.getenv("NBA_INTEREST_SCORE_THRESHOLD", "0.70"))

REALTIME_SCORING_ENABLED: bool = os.getenv("REALTIME_SCORING_ENABLED", "False").lower() in ("1", "true", "yes")
ACTIVATION_APP_WEBHOOK_URL: str | None = os.getenv("ACTIVATION_APP_WEBHOOK_URL")
