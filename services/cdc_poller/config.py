"""CDC Poller configuration — all values from environment."""

import os


# ARANGO_HOST is the CDP proxy (used by python-arango driver for AQL).
# ARANGO_RAW_HOST is the direct ArangoDB server for WAL replication API.
# These may be the same in local dev but differ in production.
ARANGO_HOST: str = os.getenv("ARANGO_HOST", "http://localhost:8529")
ARANGO_RAW_HOST: str = os.getenv("ARANGO_RAW_HOST", os.getenv("ARANGO_HOST", "http://localhost:8529"))
ARANGO_RAW_PORT: str = os.getenv("ARANGO_RAW_PORT", "8529")
ARANGO_DB: str = os.getenv("ARANGO_DB", "leo_cdp_source")
ARANGO_USER: str = os.getenv("ARANGO_USER", "root")
ARANGO_PASSWORD: str = os.getenv("ARANGO_PASSWORD", "")


def get_arango_replication_base_url() -> str:
    """Build the base URL for ArangoDB replication API with /_db/ prefix."""
    from urllib.parse import urlparse
    parsed = urlparse(ARANGO_RAW_HOST.rstrip("/"))
    # If host already includes a port, use as-is; otherwise append ARANGO_RAW_PORT
    if parsed.port:
        host = ARANGO_RAW_HOST.rstrip("/")
    else:
        host = f"{ARANGO_RAW_HOST.rstrip('/')}:{ARANGO_RAW_PORT}"
    return f"{host}/_db/{ARANGO_DB}"

REDIS_URL: str = os.getenv("REDIS_URL", "redis://localhost:6379/2")

KAFKA_BOOTSTRAP_SERVERS: str = os.getenv("KAFKA_BOOTSTRAP_SERVERS", "kafka:9092")

POLL_INTERVAL_S: int = int(os.getenv("POLL_INTERVAL_S", "2"))
BATCH_LIMIT: int = int(os.getenv("BATCH_LIMIT", "500"))
WAL_CHUNK_SIZE: int = int(os.getenv("WAL_CHUNK_SIZE", "65536"))

REALTIME_SCORING_ENABLED: bool = os.getenv("REALTIME_SCORING_ENABLED", "False").lower() in ("1", "true", "yes")

# Kafka topic for raw CDC events
CDC_TOPIC: str = "cdp.events.raw"
