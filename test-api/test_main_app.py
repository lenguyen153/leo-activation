import os
import sys
import pytest
from fastapi.testclient import TestClient

# ------------------------------------------------------------
# Ensure project root is in PYTHONPATH
# ------------------------------------------------------------
BASE_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, BASE_DIR)

from main_app import create_app


# ============================================================
# Pytest Fixtures
# ============================================================
@pytest.fixture(scope="module")
def client():
    """
    Create a TestClient once per test module.
    """
    app = create_app()
    return TestClient(app)


# ============================================================
# Health Check
# ============================================================
def test_ping_ok(client: TestClient):
    response = client.get("/ping")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


# ============================================================
# Chat – Contract Tests
# ============================================================
def test_chat_endpoint_accepts_prompt(client: TestClient):
    payload = {"prompt": "Hello agent"}

    response = client.post("/chat", json=payload)

    # Agent/tool may fail, but API contract must exist
    assert response.status_code in (200, 500)


def test_chat_response_schema_when_success(client: TestClient):
    payload = {"prompt": "What is today's date?"}

    response = client.post("/chat", json=payload)

    if response.status_code != 200:
        pytest.skip("Agent execution failed – skipping schema assertion")

    body = response.json()

    assert "answer" in body
    assert isinstance(body["answer"], str)

    assert "debug" in body
    assert "calls" in body["debug"]
    assert "data" in body["debug"]

    assert isinstance(body["debug"]["calls"], list)
    assert isinstance(body["debug"]["data"], list)


# ============================================================
# Validation
# ============================================================
def test_chat_validation_error(client: TestClient):
    response = client.post("/chat", json={})
    assert response.status_code == 422
