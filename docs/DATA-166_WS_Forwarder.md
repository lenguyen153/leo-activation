# WebSocket Forwarder

**File:** `services/ws_forwarder/consumer.py`
**Config:** `services/ws_forwarder/config.py`

## Overview

The WS Forwarder is a long-running service that maintains a single persistent outbound WebSocket connection to the other team's server (`WS_FORWARDER_URL`). It has two responsibilities:

1. **Event streaming** — forwards scored CDC events from Kafka to the other team in real time.
2. **Learning sessions** — on demand, fetches a user's ArangoDB event history and sends it as a single bulk payload.

---

## Connection & Handshake

On startup the service dials out to `WS_FORWARDER_URL` and completes a fixed handshake:

```
Leo → connect
Server → (any message)          # auth_request
Leo → {"id": "<WS_CLIENT_ID>"}
Server → {"status": "accepted"}
```

If the connection drops, the service reconnects with capped exponential back-off (`BACKOFF_BASE` → `BACKOFF_MAX` seconds).

---

## Feature 1 — Real-Time Event Streaming (Kafka → WS)

### Flow

```
CDC Poller → Kafka (leo.score.updates) → WS Forwarder → other team's WS server
```

For every Kafka message the forwarder:
1. Deserialises and scrubs PII.
2. Wraps in an envelope and sends over WS.
3. Waits for an ACK from the server before committing the Kafka offset.
4. Routes permanently failed messages to the DLQ topic.

### Outbound envelope

```json
{
  "event_id": "dev-0:123",
  "data": {
    "base_account_id": "999C000022",
    "ticker": "FPT",
    "metric_name": "ticker-view",
    "event_payload": { ... },
    "updated_at": "2026-04-20T08:30:00Z"
  },
  "sent_at": "2026-04-20T08:30:00.123Z"
}
```

`event_id` format is `<WS_FORWARDER_ENV>-<partition>:<offset>` (e.g. `dev-0:123`). Set `WS_FORWARDER_ENV=prod` in production.

### Learning mode tag

When a learning session is active for a user (see Feature 2), live Kafka events for that user have `"mode": "learning"` added to `data`:

```json
{
  "event_id": "dev-0:124",
  "data": {
    "base_account_id": "999C000022",
    "mode": "learning",
    ...
  }
}
```

### ACK protocol

The server must respond to each forwarded event with:

```json
{ "status": "ok" }
```

or

```json
{ "status": "error", "error_type": "malformed_payload", "message": "..." }
```

Any other response retries up to `MAX_SEND_RETRIES` times, then routes to DLQ.

---

## Feature 2 — Learning Sessions

The other team sends commands over the same WS connection. The forwarder listens for inbound messages with an `"action"` field and handles them alongside the normal ACK traffic via an internal demultiplexer.

### Commands

#### `start_learning`

```json
{ "action": "start_learning", "user_id": "999C000022" }
```

- Records the current UTC timestamp as `start_time` for this session.
- Adds the user to the active learning set so live Kafka events are tagged with `"mode": "learning"`.
- No DB queries are made at this point.

Multiple users can have concurrent learning sessions on the same connection.

#### `stop_learning`

```json
{ "action": "stop_learning", "user_id": "999C000022" }
```

- Records `stop_time`.
- Removes the user from the live tagging set.
- Resolves `user_id` (base_account_id) → `profile_id` via:
  ```sql
  SELECT profile_id FROM cdp_profiles
  WHERE ext_data->>'base_account_id' = '<user_id>'
  LIMIT 1
  ```
- Queries ArangoDB `cdp_trackingevent` for all events in the `[start_time, stop_time]` window:
  ```aql
  FOR event IN cdp_trackingevent
      FILTER event.refProfileId == @profile_id OR event.fingerprintId == @profile_id
      FILTER event.createdAt >= @start_time AND event.createdAt <= @stop_time
      SORT event.createdAt ASC
      RETURN { metricName, eventData, createdAt }
  ```
- Sends one bulk JSON payload back over the WS connection.

### Bulk response payload

```json
{
  "action": "learning_data",
  "user_id": "999C000022",
  "start_time": "2026-04-20T08:58:09.123456+00:00",
  "stop_time": "2026-04-20T09:05:00.654321+00:00",
  "total_events": 42,
  "events": [
    {
      "metricName": "ticker-view",
      "eventData": { "instrument_id": "FPT", "timestamp": 1713600000.0 },
      "createdAt": "2026-04-20T08:59:00.000Z"
    },
    {
      "metricName": "order-preview",
      "eventData": { "instrument_id": "VNM", "quantity": 100 },
      "createdAt": "2026-04-20T09:01:00.000Z"
    }
  ]
}
```

Events are sorted by `createdAt` ascending. Each session has its own isolated time window — events from previous sessions are never included.

### Error responses

If `user_id` cannot be resolved or ArangoDB fails:

```json
{ "action": "error", "user_id": "999C000022", "message": "No profile found for user_id '999C000022'" }
```

---

## Configuration

| Variable | Default | Description |
|---|---|---|
| `WS_FORWARDER_URL` | `wss://think-uat.innotech.vn/...` | Destination WS server URL |
| `WS_CLIENT_ID` | `cdp_innotech_2026` | Identity sent during handshake |
| `WS_FORWARDER_ENV` | _(empty)_ | Prefix for `event_id` (`dev`, `prod`). Empty = no prefix |
| `WS_ACK_TIMEOUT` | `5` | Seconds to wait for ACK before retry |
| `WS_MAX_SEND_RETRIES` | `5` | Max retries before DLQ |
| `WS_PING_INTERVAL` | `20` | WebSocket keep-alive ping interval (s) |
| `WS_PING_TIMEOUT` | `10` | WebSocket ping timeout (s) |
| `WS_FORWARDER_METRICS_PORT` | `8082` | Prometheus metrics HTTP port |

---

## Logs

| Event | Level | When |
|---|---|---|
| `ws_handshake_accepted` | info | Connection established |
| `ws_sending` | info | About to forward a Kafka event (includes payload) |
| `ack_received` | info | Server ACKed the event |
| `ws_command_received` | info | Inbound command received (`start_learning` / `stop_learning`) |
| `learning_started` | info | Session opened, `start_time` recorded |
| `learning_stop_received` | info | Session closed, ArangoDB fetch triggered |
| `learning_fetching_events` | info | PG resolved, querying ArangoDB |
| `learning_sending_data` | info | Events fetched, sending bulk payload |
| `learning_data_sent` | info | Bulk payload delivered |
| `learning_no_profile` | warning | `user_id` not found in `cdp_profiles` |
| `ws_connection_lost` | warning | WS dropped, reconnecting |
| `message_sent_to_dlq` | warning | Kafka message routed to DLQ |
