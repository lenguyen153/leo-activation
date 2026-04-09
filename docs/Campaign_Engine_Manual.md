# Campaign Engine — Operations Manual

## 1. Prerequisites

- PostgreSQL with the `campaign_rules` and `campaign_engine_runs` tables created
- Redis running (used for frequency capping and circuit breakers)
- `.env` configured with database credentials (`PGSQL_DB_*`, `ARANGO_*`, `REDIS_URL`)
- Notification channels configured in `.env` as needed (`SMTP_*`, `ZALO_*`, `ADMINNOTIFY_*`)

### Database Setup

Run the DDL script against your PostgreSQL instance:

```bash
psql -h <host> -U <user> -d leo_cdp -f sql-scripts/campaign_rules.sql
```

---

## 2. Creating a Campaign Rule

### Via API

```bash
curl -X POST http://localhost:8000/campaigns/rules \
  -H "Content-Type: application/json" \
  -d '{
    "rule_name": "Abandoned KYC Reminder",
    "channel": "push",
    "conditions": {
      "operator": "AND",
      "conditions": [
        {"field": "identities.kyc_status", "op": "eq", "value": "incomplete"},
        {"field": "event_statistics.last_login_at", "op": "newer_than_days", "value": 30}
      ]
    },
    "message_config": {
      "topic_type": "ASSISTANT_NOTIFICATION",
      "title": "Complete your KYC",
      "body": "You are almost there! Complete verification to start trading."
    },
    "frequency_cap": {"cooldown_days": 7, "max_per_day": 1},
    "schedule_cron": "0 9 * * *",
    "priority": 10
  }'
```

Rules are created in `paused` status by default.

### Via SQL (direct insert)

```sql
INSERT INTO campaign_rules (tenant_id, rule_name, conditions, channel, message_config, frequency_cap, schedule_cron, status)
VALUES (
  '<your-tenant-uuid>',
  'Sudden Inactivity',
  '{"operator":"AND","conditions":[{"field":"segments","op":"contains","value":"Active in last 3 months"},{"field":"event_statistics.last_login_at","op":"older_than_days","value":14}]}',
  'email',
  '{"subject":"We miss you!","body":"It has been a while since your last visit."}',
  '{"cooldown_days":14,"max_per_day":1}',
  '0 * * * *',
  'paused'
);
```

---

## 3. Activating a Rule

A rule will not be evaluated until its status is set to `active`:

```bash
curl -X PATCH http://localhost:8000/campaigns/rules/<rule_id>/status \
  -H "Content-Type: application/json" \
  -d '{"status": "active"}'
```

---

## 4. Preview (Dry Run)

Before activating, test how many profiles match the rule conditions. This does **not** send any notifications:

```bash
curl -X POST http://localhost:8000/campaigns/rules/<rule_id>/preview
```

Response:

```json
{
  "rule_id": "...",
  "matched_profiles": 142,
  "sample_profiles": [
    {"profile_id": "abc123", "primary_email": "user@example.com", "first_name": "Nguyen"}
  ]
}
```

---

## 5. Running the Engine

### Manual run (testing)

```bash
python -m data_workers.campaign_engine.engine
```

### Via shell script

```bash
bash shell-scripts/run_campaign_engine.sh
```

### Production: crontab (hourly)

```bash
crontab -e
```

Add the following line (runs every hour on the minute mark):

```
0 * * * * cd /path/to/leo-activation && bash shell-scripts/run_campaign_engine.sh >> /var/log/campaign_engine.log 2>&1
```

Adjust the schedule as needed. For example, to run every 30 minutes:

```
0,30 * * * * cd /path/to/leo-activation && bash shell-scripts/run_campaign_engine.sh >> /var/log/campaign_engine.log 2>&1
```

### What happens on each run

1. Loads all `campaign_rules` where `status = 'active'`
2. Filters rules whose `schedule_cron` matches the current time
3. For each rule: builds a SQL query from the condition tree, paginates matched profiles (batch size 500)
4. For each profile: checks frequency caps (Redis) → dispatches via channel → logs to `delivery_log`
5. Writes a summary row to `campaign_engine_runs`

---

## 6. Condition Tree Reference

### Leaf node

```json
{"field": "<field_path>", "op": "<operator>", "value": <value>}
```

### Logical combinators

```json
{"operator": "AND", "conditions": [ ... ]}
{"operator": "OR",  "conditions": [ ... ]}
{"operator": "NOT", "conditions": [ <single_condition> ]}
```

Nestable to any depth.

### Field paths

| Path | Resolves to |
|---|---|
| `primary_email` | `cdp_profiles.primary_email` (plain column) |
| `event_statistics.last_login_at` | `cdp_profiles.event_statistics->>'last_login_at'` (JSONB) |
| `identities.kyc_status` | `cdp_profiles.identities->>'kyc_status'` (JSONB) |
| `segments` | `cdp_profiles.segments` (JSONB array) |
| `product_recommendations.interest_score` | `product_recommendations.interest_score` (triggers JOIN) |

### Operators

| Op | Description | Example value |
|---|---|---|
| `eq` / `neq` | Equals / not equals | `"incomplete"` |
| `gt` / `gte` / `lt` / `lte` | Numeric comparison | `0.5` |
| `contains` | JSONB array contains value | `"Active in last 3 months"` |
| `not_contains` | JSONB array does not contain | `"order-created"` |
| `older_than_days` | Timestamp older than N days ago | `14` |
| `newer_than_days` | Timestamp within last N days | `30` |
| `is_null` / `is_not_null` | Null check | _(no value needed)_ |
| `in` | Value in a set | `["VN", "TH"]` |

---

## 7. Frequency Capping

Each rule has a `frequency_cap` JSONB field:

```json
{"cooldown_days": 7, "max_per_day": 1}
```

- `cooldown_days` — do not send this specific campaign to the same user again within N days
- `max_per_day` — max notifications (across all campaigns) a user can receive per day

Global defaults (overridable via `.env`):

| Variable | Default | Description |
|---|---|---|
| `CAMPAIGN_MAX_NOTIF_PER_DAY` | 3 | Global daily cap per user |
| `CAMPAIGN_MIN_COOLDOWN_HOURS` | 4 | Min gap between any two notifications to same user |

---

## 8. Circuit Breaker

If a channel (push/email/zalo) fails 5 times in a row, the circuit opens and all sends to that channel are skipped for 60 seconds. After recovery, one test send is attempted (half-open state). If it succeeds, the circuit closes.

Tunable via `.env`:

| Variable | Default |
|---|---|
| `CAMPAIGN_CB_THRESHOLD` | 5 |
| `CAMPAIGN_CB_RECOVERY_S` | 60 |

---

## 9. Monitoring

### Engine run history

```bash
curl http://localhost:8000/campaigns/rules/<rule_id>/runs?limit=10
```

### Direct SQL

```sql
-- Last 10 engine runs
SELECT run_id, started_at, finished_at, rules_evaluated, sent, skipped, errored
FROM campaign_engine_runs
ORDER BY started_at DESC
LIMIT 10;

-- Delivery log for a specific rule today
SELECT profile_id, channel, delivery_status, sent_at
FROM delivery_log
WHERE marketing_event_id LIKE 'campaign_rule_%'
  AND sent_at >= CURRENT_DATE
ORDER BY sent_at DESC;
```

### Redis keys (inspect state)

```bash
# Check a user's daily notification count
redis-cli GET "leo:notif:daily:<profile_id>:$(date +%Y-%m-%d)"

# Check campaign cooldown for a user
redis-cli GET "leo:campaign:<rule_id>:<profile_id>:last_sent"

# Check circuit breaker state
redis-cli GET "leo:circuit:push"
```

---

## 10. API Reference

| Method | Path | Description |
|---|---|---|
| `POST` | `/campaigns/rules` | Create new rule (status=paused) |
| `GET` | `/campaigns/rules` | List all rules (optional `?status=active`) |
| `GET` | `/campaigns/rules/{id}` | Get rule detail |
| `PUT` | `/campaigns/rules/{id}` | Update rule fields |
| `PATCH` | `/campaigns/rules/{id}/status` | Set status: `active`, `paused`, `archived` |
| `GET` | `/campaigns/rules/{id}/runs` | Execution history (optional `?limit=20`) |
| `POST` | `/campaigns/rules/{id}/preview` | Dry-run: matched count + sample profiles |

---

## 11. Example Campaign Rules

### Abandoned KYC

Users who signed up in the last 30 days but have not completed KYC. Push notification once a week.

```json
{
  "rule_name": "Abandoned KYC Reminder",
  "channel": "push",
  "conditions": {
    "operator": "AND",
    "conditions": [
      {"field": "identities.kyc_status", "op": "eq", "value": "incomplete"},
      {"field": "event_statistics.last_login_at", "op": "newer_than_days", "value": 30}
    ]
  },
  "message_config": {"topic_type": "ASSISTANT_NOTIFICATION", "title": "Complete your KYC", "body": "Complete verification to start trading."},
  "frequency_cap": {"cooldown_days": 7, "max_per_day": 1},
  "schedule_cron": "0 9 * * *"
}
```

### Sudden Inactivity

Active users who have not logged in for 14 days. Email once every 2 weeks.

```json
{
  "rule_name": "Sudden Inactivity Winback",
  "channel": "email",
  "conditions": {
    "operator": "AND",
    "conditions": [
      {"field": "segments", "op": "contains", "value": "Active in last 3 months"},
      {"field": "event_statistics.last_login_at", "op": "older_than_days", "value": 14}
    ]
  },
  "message_config": {"subject": "We miss you!", "body": "It has been a while since your last visit."},
  "frequency_cap": {"cooldown_days": 14, "max_per_day": 1},
  "schedule_cron": "0 * * * *"
}
```

### Viewed Ticker but Did Not Buy

Users with high interest score on a stock but no purchase. Push every 3 days.

```json
{
  "rule_name": "Viewed Ticker No Purchase",
  "channel": "push",
  "conditions": {
    "operator": "AND",
    "conditions": [
      {"field": "product_recommendations.interest_score", "op": "gte", "value": 0.5},
      {"field": "product_recommendations.recommendation_context", "op": "not_contains", "value": "order-created"}
    ]
  },
  "message_config": {"topic_type": "ASSISTANT_NOTIFICATION", "title": "Still interested?", "body": "The stock you viewed is still available."},
  "frequency_cap": {"cooldown_days": 3, "max_per_day": 2},
  "schedule_cron": "0 9 * * *"
}
```
