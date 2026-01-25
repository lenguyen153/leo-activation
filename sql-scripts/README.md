# LEO Activation – Database Technical Documentation

**System:** LEO Activation (AI-Driven Marketing & Notification Platform)
**Database:** PostgreSQL 15+ / 16
**Architecture:** Event-Driven · Agent-Oriented · Deterministic
**Scope:** Strategy → Decision → Execution → Learning
**Status:** Production-ready (Core, Governance, Experimentation)

---

## 0. Executive Summary

LEO Activation is **not** a campaign tool and **not** a message sender.

It is a **decision system** designed to repeatedly and provably answer one question:

> *Given the current state of a customer and the business,
> what is the correct action to take — and can we explain and audit that decision later?*

The database schema enforces this at the **structural level**, not by convention.

The system guarantees:

* **Correctness** – actions follow explicit rules and data
* **Explainability** – every action has a recorded reason
* **Auditability** – every decision and message is traceable
* **Reproducibility** – same inputs always yield the same outcomes

If any of these are missing, the system is **not** activation.

---

## 1. Entity Count & Coverage

**Total tables: 19**

| Domain                | Tables                                                       |
| --------------------- | ------------------------------------------------------------ |
| Core Tenancy          | `tenant`                                                     |
| Profile & Identity    | `cdp_profiles`                                               |
| Consent & Governance  | `consent_management`                                         |
| Strategy & Definition | `campaign`, `marketing_event`                                |
| Template System       | `message_templates`                                          |
| Decision Layer        | `agent_task`                                                 |
| Execution Truth       | `delivery_log`                                               |
| Segmentation          | `segment_snapshot`, `segment_snapshot_member`                |
| Experimentation       | `activation_experiments`                                     |
| Attribution           | `activation_outcomes`                                        |
| Behavioral Truth      | `behavioral_events`                                          |
| Data Lineage          | `data_sources`                                               |
| Alert & Intelligence  | `instruments`, `market_snapshot`, `alert_rules`, `news_feed` |
| Infrastructure        | `embedding_job`                                              |

This is the **minimum complete set** for a real activation system.
Fewer tables → missing capability.
More tables → unnecessary coupling.

---

## 2. Core Design Principles

### 2.1 Absolute Multi-Tenancy

* Every tenant-scoped table contains `tenant_id`
* Row Level Security (RLS) is enforced at the database layer
* Application logic is **not trusted** to enforce isolation

Session context:

```sql
SET app.current_tenant_id = '<tenant-uuid>';
```

If unset → queries return **0 rows** (fail-closed).

---

### 2.2 Root vs Tenant-Scoped Tables

Not all tables are equal.

* **Root system table:** `tenant`
* **Tenant-scoped tables:** everything else

The `tenant` table **must not depend on tenant context** for writes.
All other tables **must**.

This avoids circular dependencies and bootstrap deadlocks.

---

### 2.3 Append Truth, Never Rewrite History

* Decisions are logged, not overwritten
* Deliveries are immutable
* Behavioral events are append-only
* Corrections are new facts, not edits

History is preserved by design.

---

### 2.4 Four-Layer Activation Model

| Layer           | Responsibility         | Tables                                 |
| --------------- | ---------------------- | -------------------------------------- |
| Strategy        | Business intent        | `campaign`                             |
| Definition      | What *can* be done     | `marketing_event`, `message_templates` |
| Decision        | Why it was chosen      | `agent_task`                           |
| Execution Truth | What actually happened | `delivery_log`                         |

This separation is mandatory.

---

## 3. Core Entities

### 3.1 `tenant` – System Root

**Purpose**

* Legal, billing, and isolation boundary
* Integration anchor for Keycloak SSO

**Characteristics**

* Root table
* Partially exempt from tenant-based RLS
* No user data
* No authentication logic

Tenant creation is **admin-controlled**, not user-driven.

---

### 3.2 `cdp_profiles` – Unified Customer Snapshot

**Purpose**

* Canonical representation of a customer
* Not a “user” table

**Contains**

* Identities and contact points
* Segment membership
* Behavioral aggregates
* Vector embeddings for AI reasoning

Profiles are **re-evaluated**, not mutated.

---

### 3.3 `consent_management` – Legal Enforcement

**Purpose**

* Enforce communication rights per profile × channel

**Key rules**

* Checked **before** any activation
* Overrides campaigns, agents, and business logic

If consent is missing, the system **must not act**.

---

## 4. Strategy & Activation Definition

### 4.1 `campaign` – Business Intent

Represents **why** activation exists.

* High-level objective
* No templates
* No execution logic
* No delivery records

Examples:

* Retention of churn-risk users
* Upsell premium features

---

### 4.2 `marketing_event` – Action Definition

Represents **what may happen**.

Defines:

* Channel
* Timing
* Associated template
* Embedding for AI understanding

One campaign → many events.

---

### 4.3 `message_templates` – Message Intent

**Purpose**

* Canonical, reusable message definitions

**Supports**

* Email
* Zalo OA
* Web Push
* App Push
* WhatsApp
* Telegram
* Future channels without schema change

**Characteristics**

* Versioned
* Language-aware
* Channel-agnostic
* Metadata-driven for provider quirks

Templates define **possibility**, not execution.

---

## 5. Decision Layer (Intelligence)

### 5.1 `agent_task`

**Purpose**

* Record **why** a specific action was chosen

Stores:

* Reasoning summary
* Reasoning trace
* Inputs considered
* Outcome selected

If this table does not exist, the system is **not intelligent**, only automated.

---

## 6. Execution Truth

### 6.1 `delivery_log`

**Purpose**

* Single source of truth for outbound actions

Records:

* Who was contacted
* Through which channel
* Rendered subject and body
* Provider response
* Timestamp

If it is not in `delivery_log`, **it did not happen**.

---

## 7. Segmentation & Reproducibility

### 7.1 `segment_snapshot`

### 7.2 `segment_snapshot_member`

**Purpose**

* Freeze segment membership at decision time

Required for:

* Deterministic replay
* AI audit
* Attribution correctness

Live segments without snapshots are **not allowed** in activation.

---

## 8. Experimentation & Learning

### 8.1 `activation_experiments`

**Purpose**

* Measure effectiveness of activation decisions

Supports:

* A/B testing
* Multi-variant tests
* Bandit learning

Tracks:

* Exposure counts
* Conversion counts

No measurement → no learning → no intelligence.

---

## 9. Attribution (Why Outcomes Exist)

### 9.1 `activation_outcomes`

**Purpose**

* Explicitly link a **delivery** to an **outcome**

Answers:

> *Did this specific message cause this specific result?*

Why this is separate from `behavioral_events`:

* Behavioral events = raw facts
* Outcomes = interpreted attribution

Attribution logic evolves; raw behavior does not.

---

## 10. Behavioral & External Intelligence

### 10.1 `behavioral_events`

* Append-only
* Time-partitioned
* High volume
* User-centric

Feeds:

* Segmentation
* Agent reasoning
* Outcome attribution

---

### 10.2 Alert & Market Intelligence

| Table             | Purpose          |
| ----------------- | ---------------- |
| `instruments`     | Tracked entities |
| `market_snapshot` | Current state    |
| `alert_rules`     | Trigger logic    |
| `news_feed`       | External context |

These tables enable **context-aware activation**, not blind messaging.

---

## 11. Data Lineage & Observability

### 11.1 `data_sources`

Tracks:

* Where data originates
* Sync frequency
* Ingestion health

If data origin is unknown, AI decisions are **not trustworthy**.

---

## 12. Security & RLS Model (Summary)

* RLS enforced on all tenant-scoped tables
* Session variable `app.current_tenant_id` is mandatory
* `tenant` table:

  * RLS enabled
  * SELECT restricted
  * INSERT / UPDATE allowed for bootstrap/admin paths

Security is enforced by **structure**, not discipline.

---

## 13. Canonical Activation Flow

```
[ Behavioral Events ]
          ↓
[ CDP Profiles (Re-evaluated) ]
          ↓
[ Segment Snapshot ]
          ↓
[ Agent Task (Decision + Reasoning) ]
          ↓
[ Marketing Event + Message Templates ]
          ↓
[ Delivery Log ]
          ↓
[ Activation Outcomes ]
          ↓
[ Activation Experiments ]

```

Every arrow is traceable.
Every decision is explainable.

---

## 14. What This Schema Explicitly Does NOT Allow

This schema is designed to stop common failures by design.

It does **not allow**:

* Campaigns that send messages directly without a decision step
* Messages generated at send time without being persisted
* Messaging providers acting as the source of truth
* AI decisions that cannot be replayed or explained
* Sending first and thinking about results later

> **LEO Activation treats every message as a decision that must be owned.**

That ownership is enforced **inside the database**, where it cannot be bypassed by application code.

---

## 15. Final Architectural Statement

LEO Activation is a system that **takes responsibility for its actions**.

This schema ensures that responsibility is:

* Explicit
* Enforced
* Auditable
* Durable
* Scalable 

Anything less is not activation — it is automation without accountability.