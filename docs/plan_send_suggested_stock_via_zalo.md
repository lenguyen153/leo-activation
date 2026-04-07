# Plan: Daily Zalo Suggested Stock Dispatch (8:45 AM VN)

## Overview

A daily Celery beat job that:
1. Fetches the top 20 recommended stocks from the analysis API
2. Finds profiles interested in those stocks (interest_score ≥ 0.5) who follow the Zalo OA
3. Sends each eligible user a personalised stock suggestion via Zalo CS message

**Schedule:** 8:45 AM Vietnam (UTC+7) = **01:45 UTC**

---

## Flow

```
[Celery Beat @ 01:45 UTC]
        │
        ▼
[1] GET /api/v1/stock/recommend_stock?top_n=20
        │  → stock_map: {ticker → StockRecommendation}
        │
        ▼
[2] SQL: JOIN product_recommendations + cdp_profiles
         WHERE product_id IN (top 20 tickers)
           AND interest_score >= 0.5
           AND media_channels CONTAINS 'zalo_user_id:*'
         ORDER BY profile_id, interest_score DESC (DISTINCT ON profile_id)
        │  → rows: [{profile_id, media_channels, ticker, interest_score}]
        │
        ▼
[3] For each profile:
     ├─ Extract zalo_uid from media_channels
     ├─ Check Redis rate-limit key (1 message/user/day)
     ├─ Pick matched_stock = stock_map[row.ticker]
     ├─ Call ZaloOAChannel.send_suggested_stock(zalo_uid, SUGGESTED_STOCK_TEMPLATE, stocks=[matched_stock])
     ├─ INSERT INTO delivery_log (channel='zalo_suggested_stock')
     └─ On success: SET Redis rate-limit key (TTL 86400s)
        │
        ▼
[4] Log stats: eligible / sent / skipped / failed
```

---

## Files to Change

### `data_workers/tasks.py`

**Add SQL constant** (module-level, alongside `_ELIGIBILITY_SQL`):
```python
_SUGGESTED_STOCK_SQL = """
    SELECT DISTINCT ON (p.profile_id)
        p.profile_id,
        p.media_channels,
        r.product_id  AS ticker,
        r.interest_score
    FROM product_recommendations r
    JOIN cdp_profiles p
        ON  r.profile_id = p.profile_id
        AND r.tenant_id  = p.tenant_id
    WHERE r.tenant_id      = %s
      AND r.product_id     = ANY(%s)
      AND r.interest_score >= %s
      AND EXISTS (
            SELECT 1 FROM jsonb_array_elements_text(p.media_channels) AS ch
            WHERE ch LIKE 'zalo_user_id:%%'
          )
    ORDER BY p.profile_id, r.interest_score DESC
"""
```

**Add rate-limit key helper**:
```python
def _suggested_stock_rl_key(profile_id: str, today: str) -> str:
    return f"leo:zalo_suggested:{profile_id}:{today}"
```

**Add Celery task** `zalo_suggested_stock_dispatch`:
- Decorated with `@shared_task(bind=True, autoretry_for=(Exception,), retry_backoff=60, retry_kwargs={"max_retries": 2})`
- Accepts optional `tenant_id` kwarg (same pattern as `zalo_promo_dispatch`)
- Full implementation as described in the flow above

### `data_workers/celery_app.py`

**Add to `beat_schedule`**:
```python
"zalo-suggested-stock-daily": {
    "task": "data_workers.tasks.zalo_suggested_stock_dispatch",
    "schedule": crontab(minute="45", hour="1"),  # 01:45 UTC = 08:45 VN (UTC+7)
},
```

---

## Files Referenced (no changes)

| File | Used for |
|---|---|
| `agentic_tools/channels/zalo.py` | `ZaloOAChannel.send_suggested_stock()`, `extract_zalo_user_id()` |
| `agentic_tools/channels/templates/zalo/suggested_stock.py` | `SUGGESTED_STOCK_TEMPLATE` |
| `agentic_tools/channels/templates/zalo/models.py` | `StockRecommendation`, `ZaloSuggestedStockTemplate` |
| `agentic_tools/recommendation_system/interest_score.py` | `resolve_ids()` for tenant UUID resolution |
| `data_workers/tasks.py` (existing) | Pattern: `_rate_limit_key`, `delivery_log` INSERT, `redis_client` |

---

## Key Design Decisions

- **API called once per job run**, not per user — `stock_map` is built once and reused in the dispatch loop
- **Personalisation**: each user gets the stock they are most interested in (their highest-score ticker that appears in the top 20), not a generic top-1
- **Rate-limiting**: separate Redis key namespace (`leo:zalo_suggested:*`) to avoid collision with `zalo_promo` keys
- **Delivery logging**: uses `channel='zalo_suggested_stock'` as the channel identifier in `delivery_log`
- **Token management**: `ZaloOAChannel` is instantiated with `db_client=settings.get_arango_db()` so auto-refresh works

---

## Verification

```bash
# 1. Trigger manually
celery -A data_workers.celery_app.worker call data_workers.tasks.zalo_suggested_stock_dispatch

# 2. Confirm beat schedule loaded
celery -A data_workers.celery_app.worker inspect scheduled

# 3. Check delivery log in PostgreSQL
SELECT profile_id, marketing_event_id, delivery_status, sent_at
FROM delivery_log
WHERE channel = 'zalo_suggested_stock'
ORDER BY sent_at DESC
LIMIT 20;

# 4. Check Redis rate-limit keys
redis-cli keys "leo:zalo_suggested:*"
```
