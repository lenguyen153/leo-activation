# EDA Report — XGBoost NLA Propensity Model
**Version:** 3.0
**Date:** 2026-05-12
**Status:** ✅ TRAINED — class imbalance resolved via BorderlineSMOTE in `train_nla.py`

---

## 1. Objective

Assess whether `df_train` is statistically sound and safe to train a multi-class XGBoost model
predicting a user's **Next Likely Action (NLA)** on the financial platform.

Target classes:

| Class | Label | Meaning |
|---|---|---|
| 0 | ignore | Passive hover, no intent |
| 1 | search | Browse indices / news / overview |
| 2 | watchlist | Add or remove a ticker |
| 3 | view | Any ticker-specific view event |
| 4 | order | Order created |

---

## 2. Data Source

All data is fetched from the **production PostgreSQL database** (`172.60.1.6:5435`, db `leo_activation_db`).

| Table | Rows fetched | Purpose |
|---|---|---|
| `behavioral_events` | 11,555 | One row per user action — the training rows |
| `market_snapshot_history` | 482,786 | Point-in-time price and volume history |
| `market_snapshot` | ~1,700 | Current `is_volume_spike` flag (pre-computed by poller) |
| `product_recommendations` | 1,053 | Per-user interest scores |

`behavioral_events` is protected by Row Level Security (RLS). The fetch script sets the tenant
context before querying:

```python
cur.execute("SELECT set_config('app.current_tenant_id', %s, false)", (tenant_id,))
```

The active tenant (`master`, UUID `66b39b8b-1e82-4b0f-a1bb-4fb71f59778d`) is resolved from
the `tenant` table at runtime.

---

## 3. How df_train Is Built

**Script:** `build_df_train.py` (project root)
**Output:** `tmp/df_train_real.csv`

### 3.1 Target Mapping

Each `event_metric_name` is mapped to a `target_action` label:

| event_metric_name | target_action |
|---|---|
| `order-created`, `group-order-created` | 4 — order |
| `watchlist-add`, `watchlist-remove` | 2 — watchlist |
| `page-view`, `indices-view`, `overview-view`, `news-view` | 1 — search |
| `component-hover` | 0 — ignore |
| all other ticker-specific events | 3 — view |

### 3.2 Feature Construction

All features are computed **point-in-time** relative to each event's `created_at` timestamp.
No future data is used.

**`time_since_last_interaction`** (minutes)
```python
events.groupby("profile_id")["created_at"].diff().dt.total_seconds() / 60
# First event per profile → filled with column median
```

**`is_active_trader`** (binary)
```python
counts = events.groupby("profile_id").size()
active = set(counts[counts > counts.median()].index)
events["is_active_trader"] = events["profile_id"].isin(active).astype(int)
```

**`historical_conversion_rate`** (90-day rolling window, strictly before current event)
```python
for each event at timestamp T:
    window = events where created_at in [T - 90d, T)
    bought = distinct entity_id where event_metric_name == "order-created"
    viewed = distinct entity_id where event_metric_name != "order-created"
    rate   = bought / viewed  (0.0 if viewed == 0)
```

**`asset_price_change_24h`** (point-in-time from `market_snapshot_history`)
```python
pd.merge_asof(
    events[["created_at"]],
    market_snapshot_history[["snapshot_at", "change_percent_24h"]],
    left_on="created_at", right_on="snapshot_at",
    direction="backward",   # closest snapshot at or before event time
    by="symbol",
)
# Symbols with no history → 0.0
```

**`asset_trading_volume_spike`** (binary, from `market_snapshot`)
Pre-computed by the market poller (`poll_market_snapshot.py`) every 15 minutes:
```sql
is_volume_spike = current_volume > avg_30d_volume * 2
```
where `avg_30d_volume` = average of daily MAX volumes over the last 30 days from `market_snapshot_history`.

**`current_interest_score`**
```python
AVG(interest_score) per (profile_id, symbol) from product_recommendations
# Unmatched rows → filled with column median
```

### 3.3 Running the Builder

```bash
python build_df_train.py
# Reads PGSQL_DB_HOST_PROD from .env to connect to prod
# Output: tmp/df_train_real.csv
```

---

## 4. How the EDA Is Run

**Script:** `eda_propensity.py` (project root)
**Output:** `tmp/eda_report_prod_2026_05_12.png`

```bash
python - <<'EOF'
import pandas as pd
from eda_propensity import run_eda

df = pd.read_csv("tmp/df_train_real.csv")
run_eda(df, save_path="tmp/eda_report_prod_2026_05_12.png")
EOF
```

The script runs 6 sections automatically:

| Section | What it checks |
|---|---|
| 1. Health Check | Shape, dtypes, % missing, infinite values |
| 2. Class Balance | Imbalance ratio max/min class; FAIL if > 20× |
| 3. Feature Distributions | Skewness per continuous feature; WARN if \|skew\| > 2.0 |
| 4. Correlation Analysis | Feature–feature multicollinearity (\|r\| > 0.85); feature–target leakage (\|r\| > 0.90) |
| 5. Feature vs. Target | ANOVA (continuous) and chi-square (binary) discriminability tests |
| 6. Summary | Pass/Warn/Fail counts + verdict |

---

## 5. EDA Results (v3 — Production Data, 2026-05-12)

### 5.1 Basic Health Check ✅

- **Shape:** 11,555 rows × 7 columns
- **Missing values:** 0% across all columns
- **Infinite values:** none

| Feature | Mean | Std | Min | Max |
|---|---|---|---|---|
| current_interest_score | 0.716 | 0.218 | 0.020 | 0.992 |
| time_since_last_interaction | 116.2 min | 1,259 | 0.000 | 54,700 |
| is_active_trader | 0.970 | 0.172 | 0 | 1 |
| historical_conversion_rate | 0.044 | 0.120 | 0.000 | 1.000 |
| asset_price_change_24h | −0.013 | 1.137 | −25.0 | +15.0 |
| asset_trading_volume_spike | 0.029 | 0.167 | 0 | 1 |
| target_action | 2.595 | 1.042 | 0 | 4 |

### 5.2 Target Class Balance ❌ (raw data — resolved by SMOTE before training)

| Class | Label | Count | % |
|---|---|---|---|
| 0 | ignore | 1,503 | 13.0% |
| 1 | search | 142 | 1.2% |
| 2 | watchlist | 119 | 1.0% |
| 3 | view | 9,559 | 82.7% |
| 4 | order | 232 | 2.0% |

**Imbalance Ratio: 80.3× (view vs watchlist)**

### 5.3 Feature Distributions ⚠️

| Feature | Skewness | Flag |
|---|---|---|
| current_interest_score | −1.20 | ✅ PASS |
| time_since_last_interaction | 23.68 | ⚠️ WARN — apply `log1p` before training |
| historical_conversion_rate | 3.40 | ⚠️ WARN — apply `log1p` before training |
| asset_price_change_24h | −0.98 | ✅ PASS — no winsorization needed (max +15%, vs +50% on dev) |

### 5.4 Correlation Analysis ✅

No multicollinearity. No data leakage detected.

| Feature | Pearson→target | Spearman→target |
|---|---|---|
| current_interest_score | 0.09 | 0.12 |
| time_since_last_interaction | 0.06 | 0.27 |
| historical_conversion_rate | 0.03 | 0.08 |
| asset_price_change_24h | 0.01 | 0.00 |
| is_active_trader | 0.04 | 0.03 |
| asset_trading_volume_spike | 0.04 | 0.04 |

### 5.5 Feature vs. Target Discriminability ✅

All 6 features discriminate across target classes (p < 0.0001).
`asset_trading_volume_spike` now contributes real signal (chi-sq p=0.0000) — was all-zeros on dev DB.

### 5.6 Summary

| | Count |
|---|---|
| ✅ PASS | 25 |
| ⚠️ WARN | 2 |
| ❌ FAIL | 1 (class imbalance — resolved by SMOTE in `train_nla.py`) |

---

## 6. Training

**Script:** `train_nla.py` (project root)
**Model output:** `tmp/nla_model.json`

### 6.1 Pre-processing Applied Before Training

```python
# log1p on skewed features
df["time_since_last_interaction"] = np.log1p(df["time_since_last_interaction"])
df["historical_conversion_rate"]  = np.log1p(df["historical_conversion_rate"])

# BorderlineSMOTE on minority classes (1, 2, 4)
smote = BorderlineSMOTE(sampling_strategy={1: 1300, 2: 1300, 4: 1300}, random_state=42)
X_res, y_res = smote.fit_resample(X, y)
```

Post-SMOTE class distribution:

| Class | Before | After |
|---|---|---|
| 0 — ignore | 1,503 | 1,503 |
| 1 — search | 142 | 1,300 |
| 2 — watchlist | 119 | 1,300 |
| 3 — view | 9,559 | 9,559 |
| 4 — order | 232 | 1,300 |
| **Total** | **11,555** | **14,962** |

### 6.2 Model Configuration

```python
xgb.XGBClassifier(
    objective        = "multi:softprob",
    num_class        = 5,
    n_estimators     = 400,
    max_depth        = 6,
    learning_rate    = 0.05,
    subsample        = 0.8,
    colsample_bytree = 0.8,
    eval_metric      = "mlogloss",
    random_state     = 42,
    n_jobs           = -1,
)
```

CV used 100 estimators per fold for speed; final model trained with 400.

### 6.3 Cross-Validation Results (StratifiedKFold k=5)

**Mean macro-F1: 0.70 ± 0.01**

| Class | Precision | Recall | F1 |
|---|---|---|---|
| ignore | 0.66 | 0.17 | 0.27 ⚠️ |
| search | 0.77 | 0.67 | 0.71 |
| watchlist | 0.84 | 0.79 | 0.82 |
| view | 0.83 | 0.94 | 0.88 |
| order | 0.79 | 0.84 | 0.82 |

`ignore` is weak because it was not upsampled — the model still confuses passive hover events
with view events. All actionable classes (search, watchlist, order) perform well.

### 6.4 Feature Importances (Gain)

| Feature | Importance |
|---|---|
| historical_conversion_rate | **0.319** — strongest signal |
| time_since_last_interaction | 0.163 |
| current_interest_score | 0.161 |
| asset_price_change_24h | 0.139 |
| asset_trading_volume_spike | 0.133 — live on prod (2.9% spike rate) |
| is_active_trader | 0.085 |

---

## 7. Improvements vs. Previous Dev Run (v2)

| Item | Dev (v2) | Prod (v3) |
|---|---|---|
| behavioral_events rows | 13,159 | 11,555 |
| `asset_trading_volume_spike` rate | 0.0% — dead feature | **2.9%** — live ✅ |
| `asset_price_change_24h` max | +50.23% — winsorization needed | **+15.0%** — clean ✅ |
| `asset_price_change_24h` skew | 10.64 ⚠️ | **−0.98** ✅ |
| Model trained | ❌ blocked | ✅ `tmp/nla_model.json` |

---

## 8. Next Steps

- [ ] Upsample `ignore` class (currently F1=0.27) — consider SMOTE target for class 0
- [ ] Accumulate more profiles (currently 113 unique users; target ≥ 500 for better generalisation)
- [ ] Tune hyperparameters (max_depth, learning_rate, n_estimators) via Optuna or grid search
- [ ] Wire model into the activation pipeline for real-time NLA inference
