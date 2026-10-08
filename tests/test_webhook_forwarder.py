"""Unit tests for webhook_forwarder.deliver — no real Kafka or HTTP server needed."""

import json

import httpx
import pytest

from services.webhook_forwarder import consumer as wf


def _client(handler) -> httpx.Client:
    return httpx.Client(transport=httpx.MockTransport(handler))


@pytest.fixture(autouse=True)
def _fast_backoff(monkeypatch):
    monkeypatch.setattr(wf, "BACKOFF_BASE", 0.0)
    wf._shutdown_event.clear()
    yield
    wf._shutdown_event.clear()


def test_deliver_200_sends_ws_envelope():
    seen = []

    def handler(request):
        seen.append(request)
        return httpx.Response(200)

    payload = {"base_account_id": "999C000022", "ticker": "FPT"}
    status, error = wf.deliver(_client(handler), "dev-0:1", payload)

    assert (status, error) == (wf.DELIVERED, "")
    assert len(seen) == 1
    body = json.loads(seen[0].content)
    assert body["event_id"] == "dev-0:1"
    assert body["data"] == payload
    assert "sent_at" in body


def test_deliver_4xx_is_rejected_without_retry():
    calls = []

    def handler(request):
        calls.append(1)
        return httpx.Response(422, text="bad field")

    status, error = wf.deliver(_client(handler), "0:2", {})

    assert status == wf.REJECTED
    assert "422" in error
    assert len(calls) == 1


def test_deliver_retries_5xx_and_network_errors_until_200():
    responses = iter([
        httpx.ConnectError("down"),
        httpx.Response(503),
        httpx.Response(200),
    ])

    def handler(request):
        r = next(responses)
        if isinstance(r, Exception):
            raise r
        return r

    status, _ = wf.deliver(_client(handler), "0:3", {})
    assert status == wf.DELIVERED


def test_deliver_aborts_on_shutdown():
    def handler(request):
        wf._shutdown_event.set()
        return httpx.Response(500)

    status, _ = wf.deliver(_client(handler), "0:4", {})
    assert status == wf.ABORTED
