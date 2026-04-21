"""WebSocket Forwarder configuration — all values from environment."""

import os


KAFKA_BOOTSTRAP_SERVERS: str = os.getenv("KAFKA_BOOTSTRAP_SERVERS", "kafka:9092")

# Consumer group — distinct from the scoring consumer so both get all messages
CONSUMER_GROUP: str = "leo-ws-forwarder-v1"
INPUT_TOPIC: str = os.getenv("WS_FORWARDER_INPUT_TOPIC", "leo.score.updates")
DLQ_TOPIC: str = os.getenv("WS_FORWARDER_DLQ_TOPIC", "leo.ws-forwarder.dlq")

# Destination WebSocket
WS_URL: str = os.getenv(
    "WS_FORWARDER_URL",
    "wss://think-uat.innotech.vn/assistant/ws/event/stream",
)
WS_CLIENT_ID: str = os.getenv("WS_CLIENT_ID", "cdp_innotech_2026")
WS_HANDSHAKE_TIMEOUT: float = float(os.getenv("WS_HANDSHAKE_TIMEOUT", "10"))

# Retry / resilience knobs
ACK_TIMEOUT_SECONDS: float = float(os.getenv("WS_ACK_TIMEOUT", "5"))
MAX_SEND_RETRIES: int = int(os.getenv("WS_MAX_SEND_RETRIES", "5"))
MAX_DLQ_RETRIES: int = int(os.getenv("WS_MAX_DLQ_RETRIES", "3"))

# Exponential back-off for WS reconnection
BACKOFF_BASE: float = 1.0   # seconds
BACKOFF_MAX: float = 60.0   # cap

# Ping/Pong keep-alive interval (seconds)
WS_PING_INTERVAL: float = float(os.getenv("WS_PING_INTERVAL", "20"))
WS_PING_TIMEOUT: float = float(os.getenv("WS_PING_TIMEOUT", "10"))

# Event ID prefix — prepended to partition:offset to distinguish environments.
# e.g. WS_FORWARDER_ENV=dev  → event_id = "dev-0:123"
#      WS_FORWARDER_ENV=prod → event_id = "prod-0:123"
WS_FORWARDER_ENV: str = os.getenv("WS_FORWARDER_ENV", "")
