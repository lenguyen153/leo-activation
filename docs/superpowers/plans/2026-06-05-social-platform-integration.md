# Social Platform Integration — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add 3 focused changes to LEO Activation so the social platform can track behavioral events through the existing CDC pipeline, resolve user identity, and fetch trending tickers.

**Architecture:** Social events from Flutter (via leo-cdp-framework SDK) flow through ArangoDB → CDC poller → Kafka → scoring consumer unchanged. The scoring consumer gains a weight-override function for 9 new social metric names. Two new FastAPI routers (`/identity` and `/social`) are registered in handlers.py alongside existing routers.

**Tech Stack:** Python 3.10+, FastAPI, psycopg v3, pytest, existing `DatabaseSettings` / `get_db()` pattern from `api/audience.py`.

**Spec:** `docs/superpowers/specs/2026-06-05-social-platform-integration-design.md`

---

## File Map

| File | Action | Purpose |
|---|---|---|
| `services/scoring_consumer/consumer.py` | Modify | Add `_social_metric_score()` + integrate into main loop |
| `api/identity.py` | Create | `GET /identity/resolve` endpoint |
| `api/social.py` | Create | `GET /social/trending-tickers` endpoint |
| `api/handlers.py` | Modify | Register identity and social routers |
| `tests/test_social_event_weights.py` | Create | Unit tests for `_social_metric_score()` |
| `tests/test_identity_api.py` | Create | Integration tests for `/identity/resolve` |
| `tests/test_social_api.py` | Create | Integration tests for `/social/trending-tickers` |

---

## Task 1: Social Event Weight Function

Social events from the Flutter SDK arrive in the scoring consumer with `metric_name` values like `social_post`, `ticker_follow`, etc. The consumer currently uses `event.metric_score` (set by the CDP framework) directly. We add `_social_metric_score()` — a pure function that returns a fixed weight for known social metric names, or `None` for unknown names (letting the original CDP score pass through unchanged).

**Weight table:**

| metric_name | weight | rationale |
|---|---|---|
| `social_post` | 8.0 | Explicit ticker mention — highest intent |
| `ticker_follow` | 7.0 | Explicit subscription signal |
| `ticker_reaction` | 5.0 | Directional sentiment (bullish/bearish/like) |
| `social_share` | 5.0 | Social amplification |
| `social_bookmark` | 3.0 | Save for later |
| `discussion_comment` | 3.0 | Engaged participation |
| `ticker_page_view` | duration-scaled | `min(duration_ms, 30000) / 30000 * 2.0` |
| `social_feed_view` | duration-scaled | `min(duration_ms, 30000) / 30000 * 1.0` |
| `discussion_view` | duration-scaled | `min(duration_ms, 30000) / 30000 * 1.0` |

**Files:**
- Modify: `services/scoring_consumer/consumer.py`
- Create: `tests/test_social_event_weights.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/test_social_event_weights.py`:

```python
"""Unit tests for _social_metric_score() in the scoring consumer."""

import pytest
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from services.scoring_consumer.consumer import _social_metric_score


def test_social_post_returns_fixed_weight():
    score = _social_metric_score("social_post", {})
    assert score == pytest.approx(8.0)


def test_ticker_follow_returns_fixed_weight():
    score = _social_metric_score("ticker_follow", {})
    assert score == pytest.approx(7.0)


def test_ticker_reaction_returns_fixed_weight():
    score = _social_metric_score("ticker_reaction", {})
    assert score == pytest.approx(5.0)


def test_social_share_returns_fixed_weight():
    score = _social_metric_score("social_share", {})
    assert score == pytest.approx(5.0)


def test_social_bookmark_returns_fixed_weight():
    score = _social_metric_score("social_bookmark", {})
    assert score == pytest.approx(3.0)


def test_discussion_comment_returns_fixed_weight():
    score = _social_metric_score("discussion_comment", {})
    assert score == pytest.approx(3.0)


def test_ticker_page_view_full_duration():
    # 30 seconds or more → max weight 2.0
    score = _social_metric_score("ticker_page_view", {"duration_ms": 30000})
    assert score == pytest.approx(2.0)


def test_ticker_page_view_half_duration():
    score = _social_metric_score("ticker_page_view", {"duration_ms": 15000})
    assert score == pytest.approx(1.0)


def test_ticker_page_view_exceeds_cap():
    # duration_ms capped at 30000
    score = _social_metric_score("ticker_page_view", {"duration_ms": 999999})
    assert score == pytest.approx(2.0)


def test_ticker_page_view_zero_duration():
    score = _social_metric_score("ticker_page_view", {"duration_ms": 0})
    assert score == pytest.approx(0.0)


def test_social_feed_view_full_duration():
    score = _social_metric_score("social_feed_view", {"duration_ms": 30000})
    assert score == pytest.approx(1.0)


def test_discussion_view_half_duration():
    score = _social_metric_score("discussion_view", {"duration_ms": 15000})
    assert score == pytest.approx(0.5)


def test_unknown_metric_returns_none():
    # Non-social events must pass through unchanged
    assert _social_metric_score("ticker-view", {}) is None
    assert _social_metric_score("order-created", {}) is None
    assert _social_metric_score("watchlist-add", {}) is None


def test_missing_duration_ms_defaults_to_zero():
    score = _social_metric_score("ticker_page_view", {})
    assert score == pytest.approx(0.0)
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
cd /home/nguyen/projects/work/leo-activation
pytest tests/test_social_event_weights.py -v
```

Expected: `ImportError` or `AttributeError` — `_social_metric_score` does not exist yet.

- [ ] **Step 3: Add `_social_metric_score()` to consumer.py**

Open `services/scoring_consumer/consumer.py`. After the `_forward_pool` line (line 61), add:

```python
# --- Social event weight overrides ---
_SOCIAL_FIXED_WEIGHTS: dict[str, float] = {
    "social_post": 8.0,
    "ticker_follow": 7.0,
    "ticker_reaction": 5.0,
    "social_share": 5.0,
    "social_bookmark": 3.0,
    "discussion_comment": 3.0,
}
_SOCIAL_DURATION_WEIGHTS: dict[str, float] = {
    "ticker_page_view": 2.0,
    "social_feed_view": 1.0,
    "discussion_view": 1.0,
}


def _social_metric_score(metric_name: str, event_data: dict) -> float | None:
    """Return a fixed weight for known social metric names, or None to use CDP score."""
    if metric_name in _SOCIAL_FIXED_WEIGHTS:
        return _SOCIAL_FIXED_WEIGHTS[metric_name]
    if metric_name in _SOCIAL_DURATION_WEIGHTS:
        duration_ms = float(event_data.get("duration_ms", 0) or 0)
        capped = min(duration_ms, 30000.0)
        return (capped / 30000.0) * _SOCIAL_DURATION_WEIGHTS[metric_name]
    return None
```

- [ ] **Step 4: Integrate into the consumer main loop**

In `services/scoring_consumer/consumer.py`, find the comment `# 5. Compute incremental score` (around line 197). Change:

```python
                    # 5. Compute incremental score
                    new_raw, new_interest = compute_incremental_score(
                        current_raw, event.metric_score, prev_interaction, last_event_time
                    )
```

to:

```python
                    # 5. Compute incremental score
                    effective_score = _social_metric_score(event.metric_name, event.event_data)
                    if effective_score is None:
                        effective_score = event.metric_score
                    new_raw, new_interest = compute_incremental_score(
                        current_raw, effective_score, prev_interaction, last_event_time
                    )
```

- [ ] **Step 5: Run tests to verify they pass**

```bash
pytest tests/test_social_event_weights.py -v
```

Expected: All 14 tests PASS.

- [ ] **Step 6: Commit**

```bash
git add services/scoring_consumer/consumer.py tests/test_social_event_weights.py
git commit -m "feat: add social event weight overrides to scoring consumer"
```

---

## Task 2: Identity Resolution Endpoint

The social backend calls this once at login to map its user (identified by email or username) to a LEO `profile_id`. The endpoint queries `cdp_profiles` using `primary_email` (indexed CITEXT column) for email lookup, and the `identities` JSONB array (format: `["username:value", ...]`) for username lookup.

**Files:**
- Create: `api/identity.py`
- Modify: `api/handlers.py`
- Create: `tests/test_identity_api.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/test_identity_api.py`:

```python
"""Tests for GET /identity/resolve endpoint."""

import pytest
from fastapi.testclient import TestClient
from unittest.mock import MagicMock, patch


def _make_app():
    from api.app_factory import create_app
    return create_app()


@pytest.fixture
def client():
    app = _make_app()
    return TestClient(app)


def test_resolve_by_email_found(client):
    fake_row = {"profile_id": "U_TEST_001", "tenant_id": "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"}
    with patch("api.identity.get_db") as mock_get_db:
        mock_conn = MagicMock()
        mock_cur = MagicMock()
        mock_cur.__enter__ = lambda s: mock_cur
        mock_cur.__exit__ = MagicMock(return_value=False)
        mock_cur.fetchone.return_value = fake_row
        mock_conn.cursor.return_value = mock_cur
        mock_get_db.return_value = iter([mock_conn])
        response = client.get("/identity/resolve?email=test@example.com")
    assert response.status_code == 200
    assert response.json()["profile_id"] == "U_TEST_001"


def test_resolve_by_email_not_found(client):
    with patch("api.identity.get_db") as mock_get_db:
        mock_conn = MagicMock()
        mock_cur = MagicMock()
        mock_cur.__enter__ = lambda s: mock_cur
        mock_cur.__exit__ = MagicMock(return_value=False)
        mock_cur.fetchone.return_value = None
        mock_conn.cursor.return_value = mock_cur
        mock_get_db.return_value = iter([mock_conn])
        response = client.get("/identity/resolve?email=notfound@example.com")
    assert response.status_code == 404


def test_resolve_by_username_found(client):
    fake_row = {"profile_id": "U_TEST_002", "tenant_id": "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"}
    with patch("api.identity.get_db") as mock_get_db:
        mock_conn = MagicMock()
        mock_cur = MagicMock()
        mock_cur.__enter__ = lambda s: mock_cur
        mock_cur.__exit__ = MagicMock(return_value=False)
        mock_cur.fetchone.return_value = fake_row
        mock_conn.cursor.return_value = mock_cur
        mock_get_db.return_value = iter([mock_conn])
        response = client.get("/identity/resolve?username=myuser")
    assert response.status_code == 200
    assert response.json()["profile_id"] == "U_TEST_002"


def test_resolve_no_params_returns_400(client):
    response = client.get("/identity/resolve")
    assert response.status_code == 400


def test_resolve_both_params_uses_email(client):
    """Email takes precedence when both params are provided."""
    fake_row = {"profile_id": "U_TEST_003", "tenant_id": "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"}
    with patch("api.identity.get_db") as mock_get_db:
        mock_conn = MagicMock()
        mock_cur = MagicMock()
        mock_cur.__enter__ = lambda s: mock_cur
        mock_cur.__exit__ = MagicMock(return_value=False)
        mock_cur.fetchone.return_value = fake_row
        mock_conn.cursor.return_value = mock_cur
        mock_get_db.return_value = iter([mock_conn])
        response = client.get("/identity/resolve?email=a@b.com&username=myuser")
    assert response.status_code == 200
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
pytest tests/test_identity_api.py -v
```

Expected: `ImportError` — `api.identity` does not exist yet.

- [ ] **Step 3: Create `api/identity.py`**

```python
"""Identity resolution endpoint — maps social platform user to LEO profile_id."""

import logging
from typing import Optional

import psycopg
from fastapi import APIRouter, Depends, HTTPException, Query
from psycopg.rows import dict_row
from pydantic import BaseModel

from data_utils.settings import DatabaseSettings

logger = logging.getLogger("LEO Identity API")

router = APIRouter(prefix="/identity", tags=["Identity"])


def get_db():
    settings = DatabaseSettings()
    conn = settings.get_pg_connection_api()
    try:
        yield conn
    finally:
        conn.close()


class IdentityResponse(BaseModel):
    profile_id: str
    tenant_id: str


_SQL_BY_EMAIL = """
    SELECT profile_id, tenant_id::text
    FROM cdp_profiles
    WHERE primary_email = %(email)s
    LIMIT 1
"""

_SQL_BY_USERNAME = """
    SELECT profile_id, tenant_id::text
    FROM cdp_profiles
    WHERE identities @> to_jsonb(ARRAY['username:' || %(username)s])
    LIMIT 1
"""


@router.get("/resolve", response_model=IdentityResponse)
def resolve_identity(
    email: Optional[str] = Query(default=None),
    username: Optional[str] = Query(default=None),
    conn: psycopg.Connection = Depends(get_db),
):
    if not email and not username:
        raise HTTPException(status_code=400, detail="Provide at least one of: email, username")

    sql, params = (
        (_SQL_BY_EMAIL, {"email": email})
        if email
        else (_SQL_BY_USERNAME, {"username": username})
    )

    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(sql, params)
        row = cur.fetchone()

    if not row:
        raise HTTPException(status_code=404, detail="Profile not found")

    return IdentityResponse(profile_id=row["profile_id"], tenant_id=str(row["tenant_id"]))
```

- [ ] **Step 4: Register the router in `api/handlers.py`**

In `api/handlers.py`, add the import after the existing router imports (around line 35):

```python
from api.identity import router as identity_router
```

Then inside `create_api_router()`, after the existing `router.include_router(audience_router)` line (around line 150), add:

```python
    router.include_router(identity_router)
```

- [ ] **Step 5: Run tests to verify they pass**

```bash
pytest tests/test_identity_api.py -v
```

Expected: All 5 tests PASS.

- [ ] **Step 6: Commit**

```bash
git add api/identity.py api/handlers.py tests/test_identity_api.py
git commit -m "feat: add /identity/resolve endpoint for social platform login"
```

---

## Task 3: Trending Tickers Endpoint

Returns the tickers with the most social activity in the last 24 hours (UTC). Queries `product_recommendations` — social events flow through CDC → scoring consumer → `product_recommendations.last_interaction_at` is updated on every scored event. Grouped by `product_id` (ticker), counting distinct profiles and averaging interest score.

**Files:**
- Create: `api/social.py`
- Modify: `api/handlers.py`
- Create: `tests/test_social_api.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/test_social_api.py`:

```python
"""Tests for GET /social/trending-tickers endpoint."""

import pytest
from fastapi.testclient import TestClient
from unittest.mock import MagicMock, patch


def _make_app():
    from api.app_factory import create_app
    return create_app()


@pytest.fixture
def client():
    app = _make_app()
    return TestClient(app)


def test_trending_tickers_returns_list(client):
    fake_rows = [
        {"ticker": "VNM", "active_profiles": 42, "avg_interest_score": 0.73, "score": 30.66},
        {"ticker": "HPG", "active_profiles": 17, "avg_interest_score": 0.51, "score": 8.67},
    ]
    with patch("api.social.get_db") as mock_get_db:
        mock_conn = MagicMock()
        mock_cur = MagicMock()
        mock_cur.__enter__ = lambda s: mock_cur
        mock_cur.__exit__ = MagicMock(return_value=False)
        mock_cur.fetchall.return_value = fake_rows
        mock_conn.cursor.return_value = mock_cur
        mock_get_db.return_value = iter([mock_conn])
        response = client.get("/social/trending-tickers")
    assert response.status_code == 200
    data = response.json()
    assert isinstance(data, list)
    assert data[0]["ticker"] == "VNM"
    assert data[0]["active_profiles"] == 42


def test_trending_tickers_empty_is_valid(client):
    with patch("api.social.get_db") as mock_get_db:
        mock_conn = MagicMock()
        mock_cur = MagicMock()
        mock_cur.__enter__ = lambda s: mock_cur
        mock_cur.__exit__ = MagicMock(return_value=False)
        mock_cur.fetchall.return_value = []
        mock_conn.cursor.return_value = mock_cur
        mock_get_db.return_value = iter([mock_conn])
        response = client.get("/social/trending-tickers")
    assert response.status_code == 200
    assert response.json() == []


def test_trending_tickers_limit_param(client):
    with patch("api.social.get_db") as mock_get_db:
        mock_conn = MagicMock()
        mock_cur = MagicMock()
        mock_cur.__enter__ = lambda s: mock_cur
        mock_cur.__exit__ = MagicMock(return_value=False)
        mock_cur.fetchall.return_value = []
        mock_conn.cursor.return_value = mock_cur
        mock_get_db.return_value = iter([mock_conn])
        response = client.get("/social/trending-tickers?limit=5")
    assert response.status_code == 200


def test_trending_tickers_limit_out_of_range(client):
    response = client.get("/social/trending-tickers?limit=0")
    assert response.status_code == 422

    response = client.get("/social/trending-tickers?limit=101")
    assert response.status_code == 422
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
pytest tests/test_social_api.py -v
```

Expected: `ImportError` — `api.social` does not exist yet.

- [ ] **Step 3: Create `api/social.py`**

```python
"""Social platform read endpoints."""

import logging
from typing import List

import psycopg
from fastapi import APIRouter, Depends, HTTPException, Query
from psycopg.rows import dict_row
from pydantic import BaseModel

from data_utils.settings import DatabaseSettings

logger = logging.getLogger("LEO Social API")

router = APIRouter(prefix="/social", tags=["Social"])


def get_db():
    settings = DatabaseSettings()
    conn = settings.get_pg_connection_api()
    try:
        yield conn
    finally:
        conn.close()


class TrendingTickerItem(BaseModel):
    ticker: str
    active_profiles: int
    avg_interest_score: float
    score: float


_SQL_TRENDING = """
    SELECT
        product_id                          AS ticker,
        COUNT(DISTINCT profile_id)          AS active_profiles,
        ROUND(AVG(interest_score)::numeric, 4) AS avg_interest_score,
        ROUND(
            (COUNT(DISTINCT profile_id) * AVG(interest_score))::numeric, 4
        )                                   AS score
    FROM product_recommendations
    WHERE
        last_interaction_at > NOW() AT TIME ZONE 'UTC' - INTERVAL '24 hours'
        AND product_type = 'stock'
    GROUP BY product_id
    ORDER BY score DESC, active_profiles DESC
    LIMIT %(limit)s
"""


@router.get("/trending-tickers", response_model=List[TrendingTickerItem])
def get_trending_tickers(
    limit: int = Query(default=20, ge=1, le=100),
    conn: psycopg.Connection = Depends(get_db),
):
    try:
        with conn.cursor(row_factory=dict_row) as cur:
            cur.execute(_SQL_TRENDING, {"limit": limit})
            rows = cur.fetchall()
        return [TrendingTickerItem(**row) for row in rows]
    except Exception:
        logger.exception("Failed to fetch trending tickers")
        raise HTTPException(status_code=500, detail="Failed to fetch trending tickers")
```

- [ ] **Step 4: Register the router in `api/handlers.py`**

In `api/handlers.py`, add the import after `from api.identity import router as identity_router`:

```python
from api.social import router as social_router
```

Then inside `create_api_router()`, after `router.include_router(identity_router)`:

```python
    router.include_router(social_router)
```

- [ ] **Step 5: Run tests to verify they pass**

```bash
pytest tests/test_social_api.py -v
```

Expected: All 4 tests PASS.

- [ ] **Step 6: Run full test suite to check for regressions**

```bash
pytest tests/test_social_event_weights.py tests/test_identity_api.py tests/test_social_api.py tests/test_interest_score.py -v
```

Expected: All tests PASS.

- [ ] **Step 7: Commit**

```bash
git add api/social.py api/handlers.py tests/test_social_api.py
git commit -m "feat: add /social/trending-tickers endpoint for social platform feed"
```

---

## Final Verification

- [ ] Confirm all three new routes appear in FastAPI docs: start the server with `bash shell-scripts/start-dev.sh` and visit `/docs`
- [ ] Verify `/identity/resolve`, `/social/trending-tickers` are listed under their tags
- [ ] Verify existing `/recommendation/*`, `/audience/*`, `/campaigns/*` endpoints are unaffected
