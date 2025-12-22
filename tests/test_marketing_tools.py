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

    def fake_post(url, json, headers, timeout):
        assert "recipient" in json
        return FakeResp()

    monkeypatch.setenv("ZALO_OA_TOKEN", "fake-token")
    monkeypatch.setattr("requests.post", fake_post)

    res = mt.activate_channel("zalo", "seg_z", "promo message")
    assert res["status"] == "success"
    assert res["channel"] == "zalo_oa"
    assert "response" in res
