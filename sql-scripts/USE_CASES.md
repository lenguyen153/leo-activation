# LEO Activation – Sample Queries for Real Use Cases

> Assumption for all queries

```sql
SET app.current_tenant_id = 'a0eebc99-9c0b-4ef8-bb6d-6bb9bd380a11';
```

---

## 1. Who are my active customers and what segments are they in?

**Use case:** dashboard, targeting, debugging segmentation

```sql
SELECT
    profile_id,
    primary_email,
    first_name,
    last_name,
    segments
FROM cdp_profiles
ORDER BY profile_id;
```

---

## 2. Find all users in a specific segment (e.g. “Crypto Investor”)

**Use case:** campaign eligibility check

```sql
SELECT
    profile_id,
    primary_email,
    segments
FROM cdp_profiles
WHERE segments @> '[{"id": "CRYPTO"}]'::jsonb;
```

---

## 3. Find users at a specific journey stage

**Use case:** journey-based activation

```sql
SELECT
    profile_id,
    first_name,
    journey_maps
FROM cdp_profiles
WHERE journey_maps @> '[{"id": "J01"}]'::jsonb;
```

---

## 4. Freeze a segment snapshot (who qualified *at decision time*)

**Use case:** deterministic activation

```sql
INSERT INTO segment_snapshot (
    tenant_id,
    snapshot_id,
    segment_name,
    segment_version,
    created_at
)
VALUES (
    current_setting('app.current_tenant_id')::uuid,
    'SNAPSHOT_2026_01_01',
    'Crypto Investors',
    'v1',
    now()
)
ON CONFLICT DO NOTHING;
```

```sql
INSERT INTO segment_snapshot_member (
    tenant_id,
    snapshot_id,
    profile_id,
    created_at
)
SELECT
    tenant_id,
    'SNAPSHOT_2026_01_01',
    profile_id,
    now()
FROM cdp_profiles
WHERE segments @> '[{"id": "CRYPTO"}]'::jsonb
ON CONFLICT DO NOTHING;
```

---

## 5. Verify who was included in a snapshot

**Use case:** audit / explainability

```sql
SELECT
    m.profile_id,
    p.primary_email
FROM segment_snapshot_member m
JOIN cdp_profiles p USING (profile_id)
WHERE m.snapshot_id = 'SNAPSHOT_2026_01_01';
```

---

## 6. Check consent before activation (email example)

**Use case:** hard safety gate

```sql
SELECT
    p.profile_id,
    p.primary_email,
    c.is_allowed
FROM cdp_profiles p
LEFT JOIN consent_management c
  ON c.profile_id = p.profile_id
 AND c.channel = 'email'
WHERE p.profile_id = '00000000-0000-0000-0000-000000000001';
```

---

## 7. What messages are available for activation?

**Use case:** agent decision input

```sql
SELECT
    template_id,
    channel,
    template_name,
    version,
    status
FROM message_templates
WHERE status = 'approved';
```

---

## 8. Simulate an AI decision (log agent reasoning)

**Use case:** traceable decision making

```sql
INSERT INTO agent_task (
    tenant_id,
    task_id,
    agent_name,
    task_type,
    task_goal,
    snapshot_id,
    reasoning_summary,
    reasoning_trace,
    status,
    created_at
)
VALUES (
    current_setting('app.current_tenant_id')::uuid,
    'TASK_001',
    'segment-agent',
    'activation_decision',
    'Engage crypto investors',
    'SNAPSHOT_2026_01_01',
    'User is in crypto segment and early journey stage',
    '{"signal": ["CRYPTO", "J01"], "confidence": 0.82}'::jsonb,
    'completed',
    now()
);
```

---

## 9. Log a delivery (execution truth)

**Use case:** “what exactly did we send?”

```sql
INSERT INTO delivery_log (
    tenant_id,
    campaign_id,
    event_id,
    profile_id,
    channel,
    delivery_status,
    rendered_subject,
    rendered_body,
    sent_at,
    created_at
)
VALUES (
    current_setting('app.current_tenant_id')::uuid,
    'CMP_CRYPTO_01',
    'EVT_EMAIL_01',
    '00000000-0000-0000-0000-000000000003',
    'email',
    'SENT',
    'Bitcoin Market Update',
    'BTC halving is approaching. Here is what it means for you.',
    now(),
    now()
);
```

---

## 10. Attribute an outcome to a delivery

**Use case:** did the message work?

```sql
INSERT INTO activation_outcomes (
    tenant_id,
    delivery_id,
    profile_id,
    outcome_type,
    outcome_value,
    occurred_at
)
SELECT
    tenant_id,
    delivery_id,
    profile_id,
    'click',
    1,
    now()
FROM delivery_log
WHERE profile_id = '00000000-0000-0000-0000-000000000003'
ORDER BY sent_at DESC
LIMIT 1;
```

---

## 11. Aggregate experiment results

**Use case:** learning loop

```sql
SELECT
    campaign_id,
    variant_name,
    exposure_count,
    conversion_count,
    CASE
        WHEN exposure_count = 0 THEN 0
        ELSE conversion_count::float / exposure_count
    END AS conversion_rate
FROM activation_experiments
WHERE campaign_id = 'CMP_CRYPTO_01';
```

---

## 12. Full activation trace for a single user (end-to-end)

**Use case:** debugging, audit, support ticket

```sql
SELECT
    p.profile_id,
    a.task_id,
    d.delivery_id,
    o.outcome_type,
    o.outcome_value
FROM cdp_profiles p
LEFT JOIN agent_task a
  ON a.snapshot_id IS NOT NULL
LEFT JOIN delivery_log d
  ON d.profile_id = p.profile_id
LEFT JOIN activation_outcomes o
  ON o.delivery_id = d.delivery_id
WHERE p.profile_id = '00000000-0000-0000-0000-000000000003';
```

---

## 13. Market-driven alert test (real-time trigger validation)

**Use case:** alert engine sanity check

```sql
SELECT
    ar.rule_id,
    ar.profile_id,
    ar.symbol,
    ms.price
FROM alert_rules ar
JOIN market_snapshot ms
  ON ar.symbol = ms.symbol
WHERE ar.status = 'ACTIVE'
  AND ms.price > 150;
```

---

## Final takeaway

These queries prove that:

* Decisions are explainable
* Execution is traceable
* Attribution is explicit
* Learning is measurable
* Compliance is enforceable

If a system can answer these questions **with SQL alone**,
it is a **real activation system**, not a dashboard.

If you want next:

* Performance indexes for these queries
* Materialized views for ops
* Agent evaluation queries

Just say which.
