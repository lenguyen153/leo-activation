import os
import sys
import pytest
# Ensure project root is on path for imports
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
from agentic_tools import marketing_tools as mt

class DummyChannel(mt.NotificationChannel):
    def send(self, recipient_segment: str, message: str, **kwargs):
        return {"status": "success", "channel": "dummy", "recipient": recipient_segment, "message": message}


def test_activate_channel_invalid():
    res = mt.activate_channel("no-such-channel", "seg_a", "hello")
    assert res["status"] == "error"
    assert "available" in res


def test_register_and_execute_dummy_channel():
    # Register dummy channel and execute
    mt.ActivationManager.register_channel("dummy", DummyChannel)
    res = mt.activate_channel("dummy", "seg_b", "hi")
    assert res["status"] == "success"
    assert res["channel"] == "dummy"
    assert res["recipient"] == "seg_b"


def test_activate_channel_validation():
    # Missing message
    res = mt.activate_channel("email", "seg_c", "")
    assert res["status"] == "error"


def test_zalo_oa_send_success(monkeypatch):
    class FakeResp:
        def __init__(self):
            self.status_code = 200
        def raise_for_status(self):
            return None
        def json(self):
            return {"ok": True}

    calls = {"n": 0}

    def fake_post(url, json, headers, timeout):
        calls["n"] += 1
        assert "recipient" in json
        return FakeResp()

    monkeypatch.setenv("ZALO_OA_TOKEN", "fake-token")
    monkeypatch.setattr("requests.post", fake_post)

    res = mt.activate_channel("zalo", "seg_z", "promo message")
    assert res["status"] == "success"
    assert res["channel"] == "zalo_oa"
    assert "response" in res
    assert calls["n"] == 1


def test_zalo_oa_retries(monkeypatch):
    # Simulate first attempt failing and second succeeding
    class FailOnceResp:
        def __init__(self, fail):
            self.status_code = 200
            self._fail = fail
        def raise_for_status(self):
            if self._fail:
                raise requests.exceptions.RequestException("temporary")
            return None
        def json(self):
            return {"ok": True}

    state = {"calls": 0}

    def fake_post(url, json, headers, timeout):
        state["calls"] += 1
        if state["calls"] == 1:
            return FailOnceResp(True)
        return FailOnceResp(False)

    monkeypatch.setenv("ZALO_OA_TOKEN", "fake-token")
    monkeypatch.setattr("requests.post", fake_post)

    res = mt.activate_channel("zalo", "seg_z", "promo 2", timeout=1, retries=1)
    assert res["status"] == "success"
    assert state["calls"] == 2


def test_facebook_push_alias(monkeypatch):
    # facebook_push should be recognized and map to facebook_page channel
    res = mt.activate_channel("facebook_push", "Summer Sale Target", "Hello, this is our products")
    assert res["status"] == "success"
    assert res["channel"] == "facebook_page"


def test_zalo_oa_variants(monkeypatch):
    # Ensure spaced/hyphenated/compact variants are accepted
    monkeypatch.setenv("ZALO_OA_TOKEN", "fake-token")

    class FakeResp:
        def __init__(self):
            self.status_code = 200
        def raise_for_status(self):
            return None
        def json(self):
            return {"ok": True}

    def fake_post(url, json, headers, timeout):
        return FakeResp()

    monkeypatch.setattr("requests.post", fake_post)

    for variant in ("Zalo OA", "zalo-oa", "ZaloOA", "zalooa", "zalo oa"):
        res = mt.activate_channel(variant, "Summer Sale Target", "Hello, this is our products")
        assert res["status"] == "success"
        assert res["channel"] == "zalo_oa"
