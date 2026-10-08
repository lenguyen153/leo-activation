"""Unit tests for ws_forwarder — no real Kafka or WS server needed."""

import asyncio
import json
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from services.ws_forwarder.consumer import _send_and_wait_ack, scrub_pii


# -------------------------------------------------------------------
# scrub_pii
# -------------------------------------------------------------------
def test_scrub_pii_passthrough():
    """Default implementation returns payload unchanged."""
    payload = {"ticker": "VNM", "score": 0.85}
    assert scrub_pii(payload) == payload


# -------------------------------------------------------------------
# _send_and_wait_ack — happy path
# -------------------------------------------------------------------
@pytest.mark.asyncio
async def test_send_and_wait_ack_ok():
    """Server ACKs immediately with matching event_id."""
    ws = AsyncMock()
    ws.recv = AsyncMock(return_value=json.dumps({
        "event_id": "0:42",
        "status": "ok",
    }))

    resp = await _send_and_wait_ack(ws, "0:42", {"ticker": "VNM"})

    # Verify we sent a proper envelope
    sent = json.loads(ws.send.call_args[0][0])
    assert sent["event_id"] == "0:42"
    assert sent["data"]["ticker"] == "VNM"
    assert resp["status"] == "ok"


# -------------------------------------------------------------------
# _send_and_wait_ack — server returns wrong event_id first
# -------------------------------------------------------------------
@pytest.mark.asyncio
async def test_send_and_wait_ack_skips_unrelated():
    """Should ignore responses for other event_ids."""
    ws = AsyncMock()
    ws.recv = AsyncMock(side_effect=[
        json.dumps({"event_id": "0:99", "status": "ok"}),   # wrong id
        json.dumps({"event_id": "0:42", "status": "ok"}),   # correct
    ])

    resp = await _send_and_wait_ack(ws, "0:42", {"ticker": "VNM"})
    assert resp["event_id"] == "0:42"


# -------------------------------------------------------------------
# _send_and_wait_ack — timeout
# -------------------------------------------------------------------
@pytest.mark.asyncio
async def test_send_and_wait_ack_timeout():
    """Should raise TimeoutError when server never responds."""
    ws = AsyncMock()
    # Simulate server never responding
    ws.recv = AsyncMock(side_effect=asyncio.TimeoutError)

    with patch("services.ws_forwarder.consumer.ACK_TIMEOUT_SECONDS", 0.1):
        with pytest.raises(asyncio.TimeoutError):
            await _send_and_wait_ack(ws, "0:42", {"ticker": "VNM"})


# -------------------------------------------------------------------
# _send_and_wait_ack — malformed payload rejection
# -------------------------------------------------------------------
@pytest.mark.asyncio
async def test_send_and_wait_ack_malformed_rejection():
    """Server rejects with error_type=malformed_payload."""
    ws = AsyncMock()
    ws.recv = AsyncMock(return_value=json.dumps({
        "event_id": "0:42",
        "status": "error",
        "error_type": "malformed_payload",
        "message": "missing required field 'ticker'",
    }))

    resp = await _send_and_wait_ack(ws, "0:42", {"bad": "data"})
    assert resp["status"] == "error"
    assert resp["error_type"] == "malformed_payload"
