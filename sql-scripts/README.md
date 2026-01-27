Here is the fully updated, comprehensive **Database Technical Reference Manual** for the LEO Data Activation & Alert Center. This document serves as the single source of truth for the database schema, architectural patterns, and data flows.

---

# LEO Data Activation & Alert Center – Database Technical Reference

**Version:** 2.0 (Unified Schema)
**Database Engine:** PostgreSQL 16+
**Architecture:** Multi-tenant, Event-Driven, Hybrid (SQL + Vector + Graph)
**Primary Context:** High-frequency decisioning, AI Agent reasoning, and Financial Alerting.

---

## 1. System Architecture Overview

The database is designed not just for storage, but as an active participant in the decision loop. It enforces strict separation of concerns across four layers:

1. **Strategy Layer:** Where business intent is defined (`campaign`, `alert_rules`).
2. **Identity Layer:** The unified view of the customer (`cdp_profiles`).
3. **Intelligence Layer:** Where AI and logic live (`agent_task`, `news_feed`, `market_snapshot`).
4. **Execution Layer:** The immutable record of what happened (`delivery_log`, `behavioral_events`).

### 1.1 Key Technical Patterns

* **Absolute Multi-Tenancy:** Isolation is enforced at the row level via RLS policies.
* **Vector Native:** Embeddings are first-class citizens for RAG (Retrieval-Augmented Generation).
* **Deterministic IDs:** Critical logic uses content-hashing (SHA256) for IDs to ensure idempotency.
* **Append-Only Truth:** Historical data (snapshots, logs, behavior) is never overwritten.

---

## 2. Infrastructure & Setup

### 2.1 Required Extensions

The system relies on specific PostgreSQL extensions to function.

| Extension | Purpose |
| --- | --- |
| **`pgcrypto`** | Generates `UUIDv4` and handles SHA256 hashing for deterministic IDs. |
| **`vector`** | Enables high-dimensional vector storage (1536 dim) for Semantic Search. |
| **`citext`** | "Case-Insensitive Text" for robust email and username comparisons. |
| **`age`** | Apache AGE for Graph Database capabilities (Nodes/Edges within Postgres). |
| **`postgis`** | Spatial data support for geo-targeting. |

### 2.2 Global Utilities

* **`update_timestamp()`**: Trigger function applied to all mutable tables to auto-update the `updated_at` column.
* **`app.current_tenant_id`**: Session variable required for all queries. If unset, RLS hides all data.

---

## 3. Schema Reference: Core & Identity

### 3.1 `tenant` (Root Entity)

The root of the multi-tenant architecture. Integrates directly with Keycloak.

| Field | Type | Description |
| --- | --- | --- |
| `tenant_id` | `UUID` (PK) | Global unique identifier. |
| `tenant_name` | `TEXT` | Human-readable name (unique per realm). |
| `keycloak_realm` | `TEXT` | The Keycloak Realm this tenant belongs to. |
| `keycloak_client_id` | `TEXT` | The OIDC Client ID. |
| `metadata` | `JSONB` | Custom config (branding, limits). |
| `status` | `TEXT` | `active`, `suspended`, `archived`. |

### 3.2 `cdp_profiles` (The "User")

The unified customer profile. Synced from upstream sources (e.g., ArangoDB) but enriched locally with AI vectors and snapshots.

* **Constraint:** `segment_snapshots` is **append-only** (enforced by `prevent_snapshot_removal` trigger).

| Field | Type | Description |
| --- | --- | --- |
| `tenant_id` | `UUID` | Partition Key. |
| `profile_id` | `TEXT` (PK) | The Source ID (e.g., `U_NAM_INVESTOR`). |
| `identities` | `JSONB` | List of all known IDs (e.g., `["email:a@b.com", "crm:123"]`). |
| `primary_email` | `CITEXT` | Normalized email for lookups. |
| `living_location` | `TEXT` | Location string (e.g., "Vietnam"). |
| `job_titles` | `JSONB` | Array of titles (e.g., `["Investor", "Founder"]`). |
| `segments` | `JSONB` | Current segment membership. |
| `segment_snapshots` | `JSONB` | **Audit Trail:** Historical segment membership over time. |
| `portfolio_snapshot` | `JSONB` | Current asset holdings (Cash, Positions). |
| `portfolio_risk_score` | `NUMERIC` | 0.00 - 1.00 AI-evaluated risk tolerance. |
| `interest_embedding` | `VECTOR(1536)` | **AI Memory:** Semantic summary of user interests. |

---

## 4. Schema Reference: Strategy & Definition

### 4.1 `campaign`

High-level business initiatives.

| Field | Type | Description |
| --- | --- | --- |
| `campaign_id` | `TEXT` (PK) | Internal ID. |
| `campaign_code` | `TEXT` | Human-readable ref (e.g., `SUMMER-2026`). Unique per tenant. |
| `objective` | `TEXT` | `AWARENESS`, `CONVERSION`, etc. |
| `status` | `TEXT` | `active`, `draft`, `paused`. |

### 4.2 `marketing_event`

Specific tactical actions within a campaign.

* **Partitioning:** Hash-Partitioned by `tenant_id` (16 partitions) for scale.

| Field | Type | Description |
| --- | --- | --- |
| `event_id` | `TEXT` (PK) | Unique event identifier. |
| `event_type` | `TEXT` | `BROADCAST`, `TRIGGER`, `API`. |
| `event_channel` | `TEXT` | `EMAIL`, `SMS`, `PUSH`. |
| `embedding` | `VECTOR(1536)` | **AI Context:** Semantic vector of the event description. |

### 4.3 `message_templates`

Multi-channel content definitions. Templates are blueprints, not final messages.

| Field | Type | Description |
| --- | --- | --- |
| `template_id` | `UUID` (PK) | Unique ID. |
| `channel` | `TEXT` | `email`, `zalo_oa`, `web_push`, `whatsapp`. |
| `body_template` | `TEXT` | The raw content (Jinja2/Liquid/Handlebars). |
| `template_engine` | `TEXT` | Default `jinja2`. |
| `version` | `INT` | Version control for templates. |

---

## 5. Schema Reference: Alert Center (Financial)

### 5.1 `instruments`

Reference data for tradable assets.

| Field | Type | Description |
| --- | --- | --- |
| `symbol` | `VARCHAR` | Ticker symbol (e.g., `AAPL`, `BTC-USD`). |
| `type` | `VARCHAR` | `STOCK`, `CRYPTO`, `FX`. |
| `tenant_id` | `UUID` | If NULL, it is a global asset. If set, it's private. |

### 5.2 `market_snapshot`

Real-time pricing data. High-throughput table.

| Field | Type | Description |
| --- | --- | --- |
| `symbol` | `VARCHAR` (PK) | The asset ticker. |
| `price` | `NUMERIC` | Current market price. |
| `change_percent` | `NUMERIC` | 24h change %. |

### 5.3 `alert_rules`

User-defined or AI-generated monitoring rules.

* **Identity Generation:** `rule_id` is a SHA256 hash of (Tenant + User + Symbol + Logic). This ensures **Idempotency** (preventing duplicate alerts).

| Field | Type | Description |
| --- | --- | --- |
| `rule_id` | `VARCHAR` (PK) | **Hash:** Deterministic ID. |
| `profile_id` | `TEXT` | The user who owns this alert. |
| `symbol` | `VARCHAR` | Target asset. |
| `condition_logic` | `JSONB` | e.g., `{"operator": ">", "value": 150}`. |
| `source` | `ENUM` | `USER_MANUAL` or `AI_AGENT`. |

### 5.4 `news_feed`

Market news ingestion with AI enrichment.

| Field | Type | Description |
| --- | --- | --- |
| `news_id` | `BIGSERIAL` | Primary Key. |
| `content_embedding` | `VECTOR(1536)` | **Hybrid Search:** Used for semantic news retrieval. |
| `sentiment_score` | `NUMERIC` | AI-extracted sentiment (0.00 to 1.00). |
| `related_symbols` | `VARCHAR[]` | Assets mentioned in the news. |

---

## 6. Schema Reference: Intelligence & Execution

### 6.1 `agent_task` (The "Brain")

Stores the AI's decision-making process ("Chain of Thought").

| Field | Type | Description |
| --- | --- | --- |
| `task_id` | `TEXT` (PK) | Unique Task ID. |
| `reasoning_trace` | `JSONB` | **CoT:** The step-by-step logic the AI used. |
| `reasoning_summary` | `TEXT` | Final summary of why an action was taken. |
| `related_news_id` | `BIGINT` | Link to the news item that triggered this task. |

### 6.2 `delivery_log` (The "Hand")

The authoritative record of sent messages.

| Field | Type | Description |
| --- | --- | --- |
| `delivery_id` | `BIGSERIAL` | Primary Key. |
| `event_id` | `TEXT` | Link to Marketing Event. |
| `profile_id` | `TEXT` | Recipient. |
| `delivery_status` | `TEXT` | `sent`, `delivered`, `failed`. |
| `provider_response` | `JSONB` | Raw payload from the provider (e.g., SendGrid/Twilio). |

### 6.3 `behavioral_events` (The "Ear")

Captures user reactions.

* **Partitioning:** Range-Partitioned by **Time** (Monthly).
* **Purpose:** Feedback loop for AI training.

| Field | Type | Description |
| --- | --- | --- |
| `event_type` | `TEXT` | `VIEW`, `CLICK`, `CONVERT`. |
| `entity_type` | `TEXT` | `NEWS`, `ALERT`, `CAMPAIGN`. |
| `sentiment_val` | `INT` | +1 (Positive), -1 (Negative), 0 (Neutral). |

---

## 7. Data Flows

### 7.1 The Alert Triggering Flow

1. **Ingest:** `market_snapshot` updates via external feed.
2. **Match:** Worker polls `alert_rules` where `status='ACTIVE'` and matches symbol/condition.
3. **Trace:** `agent_task` is created to validate the alert relevance (optional AI check).
4. **Execute:** If valid, `delivery_log` is written (Notification sent).
5. **Record:** Alert status may update to `TRIGGERED`.

### 7.2 The AI Enrichment Flow

1. **New Profile:** User inserted into `cdp_profiles`.
2. **Async Job:** `embedding_job` created for the user.
3. **Process:** Worker reads `job_titles`, `interests`, `behavioral_events`.
4. **Vectorize:** Generates 1536-dim vector.
5. **Update:** Writes to `cdp_profiles.interest_embedding`.

---

## 8. Security & Compliance Model

### 8.1 Row Level Security (RLS)

* **Policy:** `tenant_select_policy`
* **Mechanism:** `USING (tenant_id = current_setting('app.current_tenant_id', true)::uuid)`
* **Effect:** A user/service can strictly ONLY see rows matching the session's tenant ID.

### 8.2 Consent Management (`consent_management`)

* **Granularity:** Per `profile_id` + `channel`.
* **Legal Basis:** Stores strict `legal_basis` (GDPR) and `source` of consent.
* **Enforcement:** Execution services must join against this table before inserting into `delivery_log`.

---

## 9. Performance Features

### 9.1 Partitioning Strategy

* **Marketing Events:** Hash Partitioned (Modulus 16). optimized for uniform distribution of massive campaign definitions.
* **Behavioral Events:** Time Partitioned (Monthly). Optimized for dropping old data (data retention) and query locality (hot recent data).

### 9.2 Indexes

* **Vector:** HNSW Index on `news_feed` and `cdp_profiles` for fast cosine similarity.
* **JSONB:** GIN Indexes on `cdp_profiles.identities` and `segments` for fast attribute lookup.
* **Graph:** AGE Catalog enabled for graph traversals.