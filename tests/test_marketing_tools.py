import os
import sys
import requests

import pytest


# ensure project root on path for imports used by tests
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))



from agentic_tools import marketing_tools as mt
from agentic_tools.channels.email import MarketingConfigs


class DummyChannel(mt.NotificationChannel):
    def send(self, recipient_segment: str, message: str, **kwargs):
        return {"status": "success", "channel": "dummy", "recipient": recipient_segment, "message": message}


def test_activate_channel_input_validation():
    # invalid channel
    res = mt.activate_channel("", "seg", "msg")
    assert res["status"] == "error"
    assert "channel" in res["message"] or "non-empty" in res["message"]

    # invalid segment
    res = mt.activate_channel("email", "", "msg")
    assert res["status"] == "error"

    # invalid message
    res = mt.activate_channel("email", "seg", "")
    assert res["status"] == "error"


def test_register_and_execute_dummy_channel():
    mt.ActivationManager.register_channel("dummy", DummyChannel)
    res = mt.activate_channel("dummy", "seg_b", "hi")
    assert res["status"] == "success"
    assert res["channel"] == "dummy"
    assert res["recipient"] == "seg_b"


def test_activation_manager_execute_unsupported_raises():
    with pytest.raises(ValueError):
        mt.ActivationManager.execute("no-such-channel", "seg", "msg")


def test_activation_manager_execute_handles_channel_exception():
    class BrokenChannel(mt.NotificationChannel):
        def send(self, recipient_segment: str, message: str, **kwargs):
            raise RuntimeError("boom")

    mt.ActivationManager.register_channel("broken", BrokenChannel)
    res = mt.ActivationManager.execute("broken", "segx", "msg")
    assert res["status"] == "error"
    assert "boom" in res["message"]


def test_zalo_oa_send_success(monkeypatch):
    # Use real channel but stub network request
    monkeypatch.setenv("ZALO_OA_TOKEN", "fake-token")

    class FakeResp:
        def __init__(self):
            self.status_code = 200

        def raise_for_status(self):
            return None

        def json(self):
            return {"ok": True}

    calls = {"n": 0}

    def fake_post(url, json=None, headers=None, timeout=None):
        calls["n"] += 1
        assert "recipient" in (json or {})
        return FakeResp()

    monkeypatch.setattr("agentic_tools.channels.zalo.requests.post", fake_post)
    res = mt.activate_channel("zalo", "seg_z", "promo message")
    assert res["status"] == "success"
    assert res["channel"] == "zalo_oa"
    assert "response" in res
    assert calls["n"] == 1


def test_zalo_oa_retries(monkeypatch):
    # simulate first attempt failing and second succeeding
    monkeypatch.setenv("ZALO_OA_TOKEN", "fake-token")

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

    def fake_post(url, json=None, headers=None, timeout=None):
        state["calls"] += 1
        if state["calls"] == 1:
            return FailOnceResp(True)
        return FailOnceResp(False)

    monkeypatch.setattr("agentic_tools.channels.zalo.requests.post", fake_post)
    res = mt.activate_channel("zalo", "seg_z", "promo 2", timeout=1, retries=1)
    assert res["status"] == "success"
    assert state["calls"] == 2


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

    def fake_post(url, json=None, headers=None, timeout=None):
        return FakeResp()

    monkeypatch.setattr("agentic_tools.channels.zalo.requests.post", fake_post)

    for variant in ("Zalo OA", "zalo-oa", "ZaloOA", "zalooa", "zalo oa", "zalo"):
        res = mt.activate_channel(variant, "Summer Sale Target", "Hello, our products")
        assert res["status"] == "success"
        assert res["channel"] == "zalo_oa"


def test_facebook_push_alias_maps_to_facebook_page(monkeypatch):
    # Replace facebook_page handler with a dummy to avoid external dependencies
    original = mt.ActivationManager.list_channels().get("facebook_page")
    class DummyFB(mt.NotificationChannel):
        def send(self, recipient_segment: str, message: str, **kwargs):
            return {"status": "success", "channel": "facebook_page", "recipient": recipient_segment, "message": message}

    try:
        mt.ActivationManager.register_channel("facebook_page", DummyFB)
        res = mt.activate_channel("facebook_push", "Summer Sale Target", "Hello, this is our products")
        assert res["status"] == "success"
        assert res["channel"] == "facebook_page"
    finally:
        if original:
            mt.ActivationManager.register_channel("facebook_page", original)


def test_email_sendgrid_requires_api_key(monkeypatch):
    # Configure for sendgrid but without API key
    monkeypatch.setattr(MarketingConfigs, "SENDGRID_API_KEY", None, raising=False)
    ch = mt.EmailChannel()
    res = ch.send("alice@example.com", "hello", provider="sendgrid", subject="Hi")
    assert res["status"] == "error"
    assert "SENDGRID_API_KEY not set" in res["message"]





def test_email_smtp_requires_credentials(monkeypatch):
    monkeypatch.setattr(MarketingConfigs, "SMTP_USERNAME", None, raising=False)
    monkeypatch.setattr(MarketingConfigs, "SMTP_PASSWORD", None, raising=False)
    ch = mt.EmailChannel()
    res = ch.send("bob@example.com", "hello smtp", provider="smtp")
    assert res["status"] == "error"
    assert "SMTP credentials not set" in res["message"]


def test_email_smtp_success_and_subject_title(monkeypatch):
    # --------------------------------------------------
    # Config
    # --------------------------------------------------
    monkeypatch.setattr(MarketingConfigs, "SMTP_USERNAME", "me@example.com", raising=False)
    monkeypatch.setattr(MarketingConfigs, "SMTP_PASSWORD", "secret", raising=False)
    monkeypatch.setattr(MarketingConfigs, "SMTP_HOST", "smtp.fake", raising=False)
    monkeypatch.setattr(MarketingConfigs, "SMTP_PORT", 587, raising=False)
    monkeypatch.setattr(MarketingConfigs, "SMTP_USE_TLS", True, raising=False)

    sent = {
        "called": False,
        "msg": None,
        "starttls": False,
        "logged_in": False,
        "login_creds": (),
    }

    # --------------------------------------------------
    # Fake SMTP client
    # --------------------------------------------------
    class FakeSMTP:
        def __init__(self, host, port, timeout=None):
            self.host = host
            self.port = port
            self.timeout = timeout

        def ehlo(self):
            pass

        def starttls(self, context=None):
            sent["starttls"] = True

        def login(self, username, password):
            sent["logged_in"] = True
            sent["login_creds"] = (username, password)

        def send_message(self, msg):
            sent["called"] = True
            sent["msg"] = msg

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

    # IMPORTANT: patch where SMTP is imported/used
    monkeypatch.setattr(
        "agentic_tools.channels.email.smtplib.SMTP",
        FakeSMTP,
    )

    # --------------------------------------------------
    # Execute: explicit subject
    # --------------------------------------------------
    ch = mt.EmailChannel()

    res = ch.send(
        recipient_segment="ignored-segment",
        message="SMTP body",
        provider="smtp",
        subject="Subj",
        recipients=["a@x.com", "b@y.com"],
    )

    assert res["status"] == "success"
    assert res["provider"] == "smtp"
    assert res["sent_to"] == ["a@x.com", "b@y.com"]

    assert sent["called"] is True
    assert sent["starttls"] is True
    assert sent["logged_in"] is True
    assert sent["login_creds"] == ("me@example.com", "secret")

    msg = sent["msg"]
    assert msg["Subject"] == "Subj"
    assert msg["To"] == "a@x.com, b@y.com"

    # --------------------------------------------------
    # Execute: fallback to title
    # --------------------------------------------------
    sent["called"] = False
    sent["msg"] = None

    res2 = ch.send(
        recipient_segment="ignored",
        message="Body two",
        provider="smtp",
        subject="MyTitle",
        recipients=["z@z.com"],
    )

    assert res2["status"] == "success"
    assert sent["called"] is True
    assert sent["msg"]["Subject"] == "MyTitle"
    assert sent["msg"]["To"] == "z@z.com"

def test_email_sendgrid_success(monkeypatch):
    # --------------------------------------------------
    # Config
    # --------------------------------------------------
    monkeypatch.setattr(MarketingConfigs, "SENDGRID_API_KEY", "fake-key", raising=False)
    monkeypatch.setattr(MarketingConfigs, "SENDGRID_FROM", "from@ex.com", raising=False)

    calls = {"n": 0}

    # --------------------------------------------------
    # Fake SendGrid response
    # --------------------------------------------------
    class FakeResp:
        def __init__(self, status=202):
            self.status_code = status
            self.text = ""

        def raise_for_status(self):
            return None

        def json(self):
            return {"ok": True}

    # --------------------------------------------------
    # Fake requests.post
    # --------------------------------------------------
    def fake_post(url, json=None, headers=None, timeout=None):
        calls["n"] += 1

        assert url == "https://api.sendgrid.com/v3/mail/send"
        assert headers is not None
        assert headers.get("Authorization") == "Bearer fake-key"
        assert headers.get("Content-Type") == "application/json"

        # payload assertions
        assert "personalizations" in json
        p = json["personalizations"][0]
        assert p["subject"] == "Greetings"
        assert p["to"] == [{"email": "alice@example.com"}]

        assert json["from"]["email"] == "from@ex.com"
        assert json["content"][0]["type"] == "text/plain"
        assert json["content"][0]["value"] == "Hello sendgrid"

        return FakeResp(202)

    monkeypatch.setattr(
        "agentic_tools.channels.email.requests.post",
        fake_post,
    )

    # --------------------------------------------------
    # Execute
    # --------------------------------------------------
    ch = mt.EmailChannel()

    res = ch.send(
        recipient_segment="ignored-segment",
        message="Hello sendgrid",
        provider="sendgrid",
        subject="Greetings",
        recipients=["alice@example.com"],
        timeout=2,
    )

    # --------------------------------------------------
    # Assertions
    # --------------------------------------------------
    assert res["status"] == "success"
    assert res["provider"] == "sendgrid"
    assert res["response_status"] == 202
    assert calls["n"] == 1

def test_email_brevo_success(monkeypatch):
    # --------------------------------------------------
    # Config
    # --------------------------------------------------
    monkeypatch.setattr(MarketingConfigs, "EMAIL_PROVIDER", "brevo", raising=False)
    monkeypatch.setattr(MarketingConfigs, "BREVO_API_KEY", "brevo-test-key", raising=False)
    monkeypatch.setattr(MarketingConfigs, "BREVO_FROM_EMAIL", "sender@example.com", raising=False)
    monkeypatch.setattr(MarketingConfigs, "BREVO_FROM_NAME", "Sender Name", raising=False)

    calls = {"n": 0}

    # --------------------------------------------------
    # Fake Brevo response
    # --------------------------------------------------
    class FakeResp:
        def __init__(self, status=201):
            self.status_code = status
            self.text = ""

        def json(self):
            return {"messageId": "brevo-msg-123"}

    # --------------------------------------------------
    # Fake requests.post
    # --------------------------------------------------
    def fake_post(url, json=None, headers=None, timeout=None):
        calls["n"] += 1

        # endpoint
        assert url == "https://api.brevo.com/v3/smtp/email"

        # headers
        assert headers is not None
        assert headers["api-key"] == "brevo-test-key"
        assert headers["content-type"] == "application/json"
        assert headers["accept"] == "application/json"

        # payload
        assert json["sender"]["email"] == "sender@example.com"
        assert json["sender"]["name"] == "Sender Name"

        assert json["to"] == [{"email": "alice@example.com"}]
        assert json["subject"] == "Hello Brevo"
        assert json["htmlContent"] == "<b>Hello Brevo</b>"

        return FakeResp(201)

    monkeypatch.setattr(
        "agentic_tools.channels.email.requests.post",
        fake_post,
    )

    # --------------------------------------------------
    # Execute
    # --------------------------------------------------
    ch = mt.EmailChannel()

    res = ch.send(
        recipient_segment="ignored-segment",
        message="<b>Hello Brevo</b>",
        provider="brevo",
        subject="Hello Brevo",
        recipients=["alice@example.com"],
        timeout=5,
    )

    # --------------------------------------------------
    # Assertions
    # --------------------------------------------------
    assert res["status"] == "success"
    assert res["provider"] == "brevo"
    assert res["message_id"] == "brevo-msg-123"
    assert calls["n"] == 1

def test_email_brevo_missing_api_key(monkeypatch):
    monkeypatch.setattr(MarketingConfigs, "EMAIL_PROVIDER", "brevo", raising=False)
    monkeypatch.setattr(MarketingConfigs, "BREVO_API_KEY", None, raising=False)
    monkeypatch.setattr(MarketingConfigs, "BREVO_FROM_EMAIL", "sender@example.com", raising=False)

    ch = mt.EmailChannel()

    res = ch.send(
        recipient_segment="ignored",
        message="<b>Hello</b>",
        provider="brevo",
        subject="Hello",
        recipients=["a@example.com"],
    )

    assert res["status"] == "error"
    assert res["provider"] == "brevo"
    assert res["message"] == "BREVO_API_KEY not set"

import requests


def test_email_brevo_network_exception(monkeypatch):
    monkeypatch.setattr(MarketingConfigs, "EMAIL_PROVIDER", "brevo", raising=False)
    monkeypatch.setattr(MarketingConfigs, "BREVO_API_KEY", "brevo-key", raising=False)
    monkeypatch.setattr(MarketingConfigs, "BREVO_FROM_EMAIL", "sender@example.com", raising=False)

    def fake_post(*args, **kwargs):
        raise requests.RequestException("Network down")

    monkeypatch.setattr(
        "agentic_tools.channels.email.requests.post",
        fake_post,
    )

    ch = mt.EmailChannel()

    res = ch.send(
        recipient_segment="ignored",
        message="<b>Hello</b>",
        provider="brevo",
        subject="Hello",
        recipients=["a@example.com"],
    )

    assert res["status"] == "error"
    assert res["provider"] == "brevo"
    assert "Network down" in res["message"]

def test_email_brevo_http_400(monkeypatch):
    monkeypatch.setattr(MarketingConfigs, "EMAIL_PROVIDER", "brevo", raising=False)
    monkeypatch.setattr(MarketingConfigs, "BREVO_API_KEY", "brevo-key", raising=False)
    monkeypatch.setattr(MarketingConfigs, "BREVO_FROM_EMAIL", "sender@example.com", raising=False)

    class FakeResp:
        status_code = 400
        text = '{"message":"Bad Request"}'

        def json(self):
            return {"message": "Bad Request"}

    def fake_post(url, json=None, headers=None, timeout=None):
        return FakeResp()

    monkeypatch.setattr(
        "agentic_tools.channels.email.requests.post",
        fake_post,
    )

    ch = mt.EmailChannel()

    res = ch.send(
        recipient_segment="ignored",
        message="<b>Hello</b>",
        provider="brevo",
        subject="Hello",
        recipients=["a@example.com"],
    )

    assert res["status"] == "error"
    assert res["provider"] == "brevo"
    assert res["http_status"] == 400
    assert "Bad Request" in res["message"]

def test_email_brevo_empty_recipients(monkeypatch):
    monkeypatch.setattr(MarketingConfigs, "EMAIL_PROVIDER", "brevo", raising=False)
    monkeypatch.setattr(MarketingConfigs, "BREVO_API_KEY", "brevo-key", raising=False)
    monkeypatch.setattr(MarketingConfigs, "BREVO_FROM_EMAIL", "sender@example.com", raising=False)

    ch = mt.EmailChannel()

    res = ch.send(
        recipient_segment="ignored",
        message="<b>Hello</b>",
        provider="brevo",
        subject="Hello",
        recipients=[],
    )

    assert res["status"] == "error"
    assert res["provider"] == "brevo"
    assert res["message"] == "Recipient list is empty"
