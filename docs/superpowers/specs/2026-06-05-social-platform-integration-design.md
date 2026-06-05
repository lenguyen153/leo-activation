# Social Platform Integration Design
**Date:** 2026-06-05
**Status:** Approved

---

## 1. Context

LEO Activation is an agentic marketing backend serving the LEO CDP. A new product — a social media platform focused on stock discussions and social feed — is being built as a **separate product on the same tenant**. This document defines how the two systems integrate.

---

## 2. Product Overview

**Social Platform core features:**
- Social feed — users post, follow, and comment on stock-related content
- Stock discussions — threaded conversations anchored to specific tickers

**Tech stack:**
- Flutter frontend (mobile)
- Separate backend (own language/framework, own DB)
- RabbitMQ for async writes (post, like, react, comment, share, bookmark, follow)
- Connects to LEO Activation via REST API only

---

## 3. Integration Model

**Same tenant, separate product.** The social platform shares the same `tenant_id` in PostgreSQL but runs its own stack. It is not a LEO Activation module — it is a consumer of LEO data and a producer of behavioral signals.

### 3.1 Data Flow

**Write path (behavioral events):**
```
Flutter App
  → leo-cdp-framework SDK (offline-safe, auto-retry)
  → ArangoDB
  → LEO Activation CDC poller (existing)
  → Kafka → Scoring Consumer → PostgreSQL
```

**Read path (recommendations):**
```
Social Backend → LEO Activation REST API
  GET /recommendation/interested/{ticker}
  GET /recommendation/profile_affinity/{profile_id}
  GET /recommendation/nba/{profile_id}
  GET /social/trending-tickers          ← new
```

**Identity path (one-time at login):**
```
Social Backend → GET /identity/resolve?email= | ?username=
              ← { profile_id, tenant_id }
Social Backend caches profile_id locally — does not call again per session
```

### 3.2 Event Tracking Strategy

Flutter uses the **leo-cdp-framework SDK** (Dart/Flutter native) to track all events. The SDK handles offline queuing and auto-retry — no custom retry logic needed in the social platform.

The social backend's **RabbitMQ** pipeline is not involved in CDP tracking. RabbitMQ handles the social platform's own async writes (to its own DB). The two systems are independent.

---

## 4. New Event Types

All events are tracked from the Flutter app via the leo-cdp-framework SDK. Each includes `profile_id`, `tenant_id`, and `ticker` where applicable.

### High-Signal Events (explicit user intent)

| Event type | Payload | Score weight |
|---|---|---|
| `social_post` | `{ticker, sentiment}` | High |
| `ticker_follow` | `{ticker}` | High |
| `ticker_reaction` | `{ticker, reaction: bullish\|bearish\|like}` | Medium-high |
| `social_share` | `{ticker}` | Medium-high |
| `social_bookmark` | `{ticker}` | Medium |
| `discussion_comment` | `{ticker, thread_id}` | Medium |

### Low-Signal Events (passive engagement)

| Event type | Payload | Score weight |
|---|---|---|
| `ticker_page_view` | `{ticker, duration_ms}` | Low — scaled by `min(duration_ms, 30000)` |
| `social_feed_view` | `{ticker, duration_ms, position}` | Low — scaled by duration |
| `discussion_view` | `{ticker, thread_id, duration_ms}` | Low — scaled by duration |

Duration scaling: weight = `base_weight × min(duration_ms, 30000) / 30000`. This prevents passive-scroll inflation.

---

## 5. Changes to LEO Activation

### 5.1 Scoring Consumer — new event weights
**File:** `services/scoring_consumer/consumer.py`

Add weight mappings for the 9 new social event types. Extend the existing event-type → weight dispatch logic with `elif` branches. No structural changes.

### 5.2 Identity Resolution Endpoint
**New file:** `api/identity.py`

```
GET /identity/resolve?email=<email>
GET /identity/resolve?username=<username>

Response: { "profile_id": "...", "tenant_id": "..." }
Errors:   404 if not found, 400 if neither param provided
```

- Queries PostgreSQL `profile` table by `email` or `username` (`display_name` is not a lookup key)
- Respects existing RLS — tenant-scoped query
- Register router in `api/handlers.py` under prefix `/identity`

### 5.3 Trending Tickers Endpoint
**New file:** `api/social.py`

```
GET /social/trending-tickers?limit=20

Response: [{ "ticker": "VNM", "post_count": 142, "reaction_count": 89, "score": 9.4 }]
```

- Aggregates social event counts from PostgreSQL scoring/event tables over a rolling 24h window (UTC)
- Score = weighted sum of `social_post`, `ticker_reaction`, `discussion_comment` counts
- Register router in `api/handlers.py` under prefix `/social`

---

## 6. What Does NOT Change in LEO Activation

- CDC poller, ArangoDB sync, Kafka pipeline
- NBA / NLA engines
- Campaign engine and cron scheduler
- React dashboard
- All existing `/recommendation/*`, `/audience/*`, `/portfolio/*` endpoints

---

## 7. Social Platform Owns Entirely

| Component | Responsibility |
|---|---|
| Flutter App | UI, feed rendering, discussion threads, posting, reactions, leo-cdp-framework SDK calls |
| Social Backend | Post/comment/reaction CRUD, follow graph, feed ranking, push notifications, RabbitMQ async writes |
| Social DB | Posts, comments, reactions, follows, bookmarks, shares |
| Identity cache | Maps social user ID ↔ profile_id, looked up once at login via `/identity/resolve` and cached locally |

---

## 8. Out of Scope

- Campaign engine integration with the social platform
- Real-time event streaming to the social platform (WebSocket / SSE)
- Social graph stored in LEO Activation's PG
- Moderation or content filtering in LEO Activation

---

## 9. Resolved Decisions

- **Identity lookup fields:** `email` and `username` only — no phone field exists in the profile table
- **Trending tickers window:** UTC
- **Auth:** All endpoints are protected by Keycloak at the infrastructure level — no per-endpoint auth logic needed
