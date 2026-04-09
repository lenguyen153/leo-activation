"""
Redis-backed circuit breaker per notification channel.

States: closed → open → half_open → closed
- Closed:    normal operation. Track consecutive failures.
- Open:      skip all sends. Auto-transition to half_open after RECOVERY_S.
- Half-open: allow 1 test send. Success → closed, failure → open.

Redis key: leo:circuit:{channel}
Value:     JSON {failures, last_failure, state}
TTL:       300s (auto-reset safety net)
"""

import json
import logging
import time

from main_configs import CampaignEngineConfigs

logger = logging.getLogger(__name__)

_TTL = 300  # seconds — auto-expire as safety net


def _get_state(redis_client, channel: str) -> dict:
    key = f"leo:circuit:{channel}"
    raw = redis_client.get(key)
    if not raw:
        return {"failures": 0, "last_failure": 0.0, "state": "closed"}
    return json.loads(raw.decode() if isinstance(raw, bytes) else raw)


def _set_state(redis_client, channel: str, state: dict) -> None:
    key = f"leo:circuit:{channel}"
    redis_client.setex(key, _TTL, json.dumps(state))


def is_channel_available(redis_client, channel: str) -> bool:
    """Check whether the circuit allows sending on this channel."""
    state = _get_state(redis_client, channel)

    if state["state"] == "closed":
        return True

    if state["state"] == "open":
        elapsed = time.time() - state["last_failure"]
        if elapsed >= CampaignEngineConfigs.CIRCUIT_BREAKER_RECOVERY_S:
            # Transition to half-open
            state["state"] = "half_open"
            _set_state(redis_client, channel, state)
            logger.info("[CircuitBreaker] %s → half_open (recovery period elapsed)", channel)
            return True
        return False

    # half_open — allow exactly one probe
    return True


def record_success(redis_client, channel: str) -> None:
    """Reset circuit to closed on successful send."""
    state = _get_state(redis_client, channel)
    if state["state"] != "closed":
        logger.info("[CircuitBreaker] %s → closed (success)", channel)
    _set_state(redis_client, channel, {"failures": 0, "last_failure": 0.0, "state": "closed"})


def record_failure(redis_client, channel: str) -> None:
    """Increment failure count; open circuit if threshold exceeded."""
    state = _get_state(redis_client, channel)

    if state["state"] == "half_open":
        # Probe failed — back to open
        state["state"] = "open"
        state["last_failure"] = time.time()
        _set_state(redis_client, channel, state)
        logger.warning("[CircuitBreaker] %s → open (half_open probe failed)", channel)
        return

    state["failures"] += 1
    state["last_failure"] = time.time()

    if state["failures"] >= CampaignEngineConfigs.CIRCUIT_BREAKER_THRESHOLD:
        state["state"] = "open"
        logger.warning(
            "[CircuitBreaker] %s → open (%d consecutive failures)",
            channel, state["failures"],
        )

    _set_state(redis_client, channel, state)
