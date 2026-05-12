# EDA Pipeline for XGBoost NLA Propensity Model

## Context
Before training a multi-class XGBoost model predicting Next Likely Action (0–4), we need to verify
`df_train` is statistically sound, free of leakage, and has manageable class imbalance.
This EDA script produces all artifacts needed for a "go / no-go" training decision.

**Script:** `eda_propensity.py` (project root)

---

## Part A — Python EDA Script

```python
"""
EDA Pipeline for XGBoost NLA Propensity Model
Assess if df_train is healthy enough to train a reliable multi-class classifier.

Usage:
    # With your real DataFrame:
    from eda_propensity import run_eda
    run_eda(df_train)

    # Standalone with synthetic data for testing:
    python eda_propensity.py
"""

import numpy as np
import pandas as pd
import matplotlib.pyplot as plt
import matplotlib.gridspec as gridspec
import seaborn as sns
from scipy import stats

# ─── Config ───────────────────────────────────────────────────────────────────
CONTINUOUS_FEATURES = [
    "current_interest_score",
    "time_since_last_interaction",
    "historical_conversion_rate",
    "asset_price_change_24h",
]
BINARY_FEATURES = [
    "is_active_trader",
    "asset_trading_volume_spike",
]
TARGET = "target_action"
TARGET_LABELS = {0: "ignore", 1: "search", 2: "watchlist", 3: "view", 4: "order"}
ALL_FEATURES = CONTINUOUS_FEATURES + BINARY_FEATURES

# Thresholds for flag logic
NAN_WARN_PCT          = 5.0   # % missing → WARN
NAN_FAIL_PCT          = 20.0  # % missing → FAIL
IMBALANCE_WARN        = 5.0   # ratio max/min class → WARN
IMBALANCE_FAIL        = 20.0  # ratio → FAIL
SKEW_WARN             = 2.0   # |skewness| → WARN (log-transform likely needed)
CORR_MULTICOLLINEARITY = 0.85 # feature-feature |corr| → WARN
CORR_LEAKAGE          = 0.90  # feature-target |corr| → FAIL (data leakage)
REPORT_PATH           = "eda_report.png"

sns.set_theme(style="whitegrid", palette="muted")

# ─── Flag logger ──────────────────────────────────────────────────────────────
_PASS = "✅ PASS"
_WARN = "⚠️  WARN"
_FAIL = "❌ FAIL"
_flags: list[tuple[str, str, str]] = []   # (check, flag, detail)

def _log(check: str, flag: str, detail: str) -> None:
    _flags.append((check, flag, detail))
    print(f"  {flag}  {check}: {detail}")


# ─── Section 1: Basic Health Check ───────────────────────────────────────────
def _check_health(df: pd.DataFrame) -> None:
    print("\n" + "=" * 60)
    print("SECTION 1 — BASIC HEALTH CHECK")
    print("=" * 60)
    print(f"  Shape      : {df.shape[0]:,} rows × {df.shape[1]} cols")
    print(f"  dtypes     :\n{df.dtypes.to_string()}\n")
    print("  Descriptive statistics:")
    print(df[ALL_FEATURES + [TARGET]].describe().round(4).to_string())

    # Missing values
    print("\n  Missing Values:")
    nan_pct = df.isnull().mean() * 100
    for col in ALL_FEATURES + [TARGET]:
        pct = nan_pct[col]
        if pct >= NAN_FAIL_PCT:
            _log(f"NaN [{col}]", _FAIL, f"{pct:.1f}% missing — drop or impute urgently")
        elif pct >= NAN_WARN_PCT:
            _log(f"NaN [{col}]", _WARN, f"{pct:.1f}% missing — investigate before training")
        else:
            _log(f"NaN [{col}]", _PASS, f"{pct:.1f}% missing")

    # Infinite values (crash XGBoost silently)
    print("\n  Infinite Values:")
    for col in CONTINUOUS_FEATURES:
        n_inf = np.isinf(df[col].replace([None], np.nan).dropna()).sum()
        if n_inf > 0:
            _log(f"Inf [{col}]", _FAIL, f"{n_inf} infinite values — will break XGBoost")
        else:
            _log(f"Inf [{col}]", _PASS, "no infinite values")


# ─── Section 2: Target Class Balance ─────────────────────────────────────────
def _check_class_balance(df: pd.DataFrame, ax: plt.Axes) -> None:
    print("\n" + "=" * 60)
    print("SECTION 2 — TARGET CLASS BALANCE")
    print("=" * 60)

    counts = df[TARGET].value_counts().sort_index()
    pcts   = df[TARGET].value_counts(normalize=True).sort_index() * 100

    print(f"  {'Class':<10} {'Label':<12} {'Count':>8} {'%':>8}")
    print(f"  {'-'*42}")
    for cls, cnt in counts.items():
        print(f"  {cls:<10} {TARGET_LABELS[cls]:<12} {cnt:>8,} {pcts[cls]:>7.1f}%")

    ratio = counts.max() / counts.min()
    print(f"\n  Imbalance Ratio (max/min class): {ratio:.1f}x")

    if ratio >= IMBALANCE_FAIL:
        _log("Class Imbalance", _FAIL,
             f"{ratio:.1f}x — use SMOTE or class-level oversampling; "
             "scale_pos_weight alone is insufficient for multi-class at this skew")
    elif ratio >= IMBALANCE_WARN:
        _log("Class Imbalance", _WARN,
             f"{ratio:.1f}x — set sample_weight or use stratified k-fold CV")
    else:
        _log("Class Imbalance", _PASS, f"{ratio:.1f}x — acceptable")

    # Plot
    bars = ax.bar(
        [f"{k}\n({TARGET_LABELS[k]})" for k in counts.index],
        counts.values,
        color=sns.color_palette("muted", len(counts)),
        edgecolor="white",
    )
    for bar, pct in zip(bars, pcts):
        ax.text(
            bar.get_x() + bar.get_width() / 2,
            bar.get_height() + counts.max() * 0.01,
            f"{pct:.1f}%", ha="center", va="bottom", fontsize=9,
        )
    ax.set_title("Target Class Distribution", fontweight="bold")
    ax.set_xlabel("target_action")
    ax.set_ylabel("Count")


# ─── Section 3: Feature Distributions ────────────────────────────────────────
def _plot_distributions(df: pd.DataFrame, axes_cont: list, axes_bin: list) -> None:
    print("\n" + "=" * 60)
    print("SECTION 3 — FEATURE DISTRIBUTIONS")
    print("=" * 60)

    for ax, col in zip(axes_cont, CONTINUOUS_FEATURES):
        data = df[col].dropna()
        skew = data.skew()
        sns.histplot(data, kde=True, ax=ax, bins=40, color="steelblue", edgecolor="none")
        ax.set_title(f"{col}\nskew={skew:.2f}", fontsize=9, fontweight="bold")
        ax.set_xlabel("")

        if abs(skew) >= SKEW_WARN:
            _log(f"Skew [{col}]", _WARN,
                 f"|skew|={abs(skew):.2f} — consider log/power transform before training")
        else:
            _log(f"Skew [{col}]", _PASS, f"skew={skew:.2f}")

    for ax, col in zip(axes_bin, BINARY_FEATURES):
        rate = df[col].mean() * 100
        sns.countplot(x=df[col], ax=ax, palette="muted", edgecolor="white")
        ax.set_title(f"{col}\npositive rate: {rate:.1f}%", fontsize=9, fontweight="bold")
        ax.set_xlabel("")


# ─── Section 4: Correlation Analysis ─────────────────────────────────────────
def _plot_correlations(
    df: pd.DataFrame, ax_pearson: plt.Axes, ax_spearman: plt.Axes
) -> None:
    print("\n" + "=" * 60)
    print("SECTION 4 — CORRELATION ANALYSIS")
    print("=" * 60)

    cols = ALL_FEATURES + [TARGET]
    pearson  = df[cols].corr(method="pearson")
    spearman = df[cols].corr(method="spearman")
    mask = np.triu(np.ones_like(pearson, dtype=bool))

    def _hmap(ax, corr, title):
        sns.heatmap(
            corr, mask=mask, ax=ax, annot=True, fmt=".2f",
            cmap="coolwarm", center=0, vmin=-1, vmax=1,
            linewidths=0.5, annot_kws={"size": 7},
            cbar_kws={"shrink": 0.8},
        )
        ax.set_title(title, fontweight="bold")

    _hmap(ax_pearson,  pearson,  "Pearson Correlation")
    _hmap(ax_spearman, spearman, "Spearman Correlation")

    # Multicollinearity: feature-feature pairs
    print("  Feature–Feature (Pearson):")
    for i, f1 in enumerate(ALL_FEATURES):
        for f2 in ALL_FEATURES[i + 1:]:
            r = abs(pearson.loc[f1, f2])
            if r >= CORR_MULTICOLLINEARITY:
                _log(f"Multicollinearity [{f1} × {f2}]", _WARN,
                     f"|r|={r:.2f} — drop one or run VIF analysis")

    # Leakage: feature-target
    print("\n  Feature–Target Correlations:")
    for col in ALL_FEATURES:
        r_p = abs(pearson.loc[col, TARGET])
        r_s = abs(spearman.loc[col, TARGET])
        r_max = max(r_p, r_s)
        if r_max >= CORR_LEAKAGE:
            _log(f"Leakage [{col}]", _FAIL,
                 f"|r|={r_max:.2f} — verify this feature is NOT computed after the event "
                 "(point-in-time violation)")
        else:
            _log(f"Corr [{col}→target]", _PASS,
                 f"Pearson={r_p:.2f}, Spearman={r_s:.2f}")


# ─── Section 5: Feature vs. Target ───────────────────────────────────────────
def _plot_feature_vs_target(df: pd.DataFrame, axes: list) -> None:
    print("\n" + "=" * 60)
    print("SECTION 5 — FEATURE VS. TARGET (DISCRIMINABILITY)")
    print("=" * 60)

    ax_idx = 0
    order  = sorted(df[TARGET].unique())
    xlabels = [f"{k}\n({TARGET_LABELS[k]})" for k in order]

    # Continuous: boxplot + one-way ANOVA
    for col in CONTINUOUS_FEATURES:
        ax = axes[ax_idx]; ax_idx += 1
        sns.boxplot(data=df, x=TARGET, y=col, ax=ax,
                    palette="muted", showfliers=False, order=order)
        ax.set_xticklabels(xlabels, fontsize=7)

        groups = [df[df[TARGET] == k][col].dropna() for k in order]
        f_stat, p_val = stats.f_oneway(*groups)
        sig = "✓ discriminates" if p_val < 0.05 else "✗ no signal"
        ax.set_title(f"{col}\nANOVA F={f_stat:.1f} p={p_val:.3f} {sig}",
                     fontsize=8, fontweight="bold")
        ax.set_xlabel("")

        if p_val >= 0.05:
            _log(f"ANOVA [{col}]", _WARN,
                 f"p={p_val:.3f} — feature does NOT vary across target classes")
        else:
            _log(f"ANOVA [{col}]", _PASS, f"p={p_val:.4f} — feature discriminates classes")

    # Binary: proportion bar + chi-square
    for col in BINARY_FEATURES:
        ax = axes[ax_idx]; ax_idx += 1
        ct = pd.crosstab(df[TARGET], df[col], normalize="index") * 100
        ct.plot(kind="bar", stacked=True, ax=ax,
                colormap="coolwarm", edgecolor="white", legend=True)
        ax.set_xticklabels(xlabels, rotation=0, fontsize=7)
        contingency = pd.crosstab(df[TARGET], df[col])
        chi2, p_val, _, _ = stats.chi2_contingency(contingency)
        sig = "✓ associated" if p_val < 0.05 else "✗ no signal"
        ax.set_title(f"{col} (% per class)\nχ²={chi2:.1f} p={p_val:.3f} {sig}",
                     fontsize=8, fontweight="bold")
        ax.set_xlabel("")
        ax.legend(title=col, fontsize=7, title_fontsize=7)

        if p_val >= 0.05:
            _log(f"Chi-sq [{col}]", _WARN,
                 f"p={p_val:.3f} — binary feature shows no significant association with target")
        else:
            _log(f"Chi-sq [{col}]", _PASS,
                 f"p={p_val:.4f} — significant association with target")


# ─── Section 6: Final Summary ─────────────────────────────────────────────────
def _print_summary() -> None:
    print("\n" + "=" * 60)
    print("SECTION 6 — FINAL CHECKLIST SUMMARY")
    print("=" * 60)

    fails  = [(c, d) for c, f, d in _flags if f == _FAIL]
    warns  = [(c, d) for c, f, d in _flags if f == _WARN]
    passes = [(c, d) for c, f, d in _flags if f == _PASS]

    print(f"\n  {_PASS}  {len(passes)} checks passed")
    print(f"  {_WARN}  {len(warns)} warnings")
    print(f"  {_FAIL}  {len(fails)} failures\n")

    if fails:
        print("  ── FAILURES (resolve before training) ──")
        for check, detail in fails:
            print(f"     • {check}: {detail}")
    if warns:
        print("\n  ── WARNINGS (investigate before training) ──")
        for check, detail in warns:
            print(f"     • {check}: {detail}")

    # Point-in-time checks — always printed; require manual verification
    print("\n  ── Point-in-Time Correctness (manual verification required) ──")
    pit_checks = [
        ("current_interest_score",
         "must be computed from events BEFORE the target event timestamp"),
        ("asset_price_change_24h",
         "must use market_snapshot_history at event time, NOT the current snapshot"),
        ("time_since_last_interaction",
         "delta must be relative to event time, not 'now' at feature-generation time"),
        ("historical_conversion_rate",
         "window must EXCLUDE the current event — e.g., T-1d to T-90d"),
        ("asset_trading_volume_spike",
         "30d avg baseline must be computed before the event date"),
    ]
    for col, note in pit_checks:
        print(f"     • {col}: {note}")

    verdict = (
        "❌ DO NOT TRAIN — resolve failures first"  if fails else
        "⚠️  TRAIN WITH CAUTION — address warnings" if warns else
        "✅ READY TO TRAIN"
    )
    print(f"\n  ══ VERDICT: {verdict} ══\n")


# ─── Public entry point ───────────────────────────────────────────────────────
def run_eda(df: pd.DataFrame, save_path: str = REPORT_PATH) -> None:
    """
    Run the full EDA pipeline on df_train.

    Args:
        df:        Training DataFrame produced by the DE team.
        save_path: Path to save the composite figure (PNG).
    """
    _flags.clear()

    # Build composite figure
    fig = plt.figure(figsize=(22, 30))
    fig.suptitle(
        "NLA Propensity Model — EDA Report", fontsize=16, fontweight="bold", y=0.99
    )
    gs = gridspec.GridSpec(5, 4, figure=fig, hspace=0.55, wspace=0.4)

    ax_balance   = fig.add_subplot(gs[0, :])
    axes_cont    = [fig.add_subplot(gs[1, i]) for i in range(4)]
    axes_bin     = [fig.add_subplot(gs[2, i]) for i in range(2)]
    ax_pearson   = fig.add_subplot(gs[3, :2])
    ax_spearman  = fig.add_subplot(gs[3, 2:])
    axes_fvt     = [fig.add_subplot(gs[4, i]) for i in range(4)]

    # Continuous FvT fills row 4; binary FvT gets inset axes below
    ax_bfvt0 = fig.add_axes([0.05, 0.005, 0.42, 0.095])
    ax_bfvt1 = fig.add_axes([0.54, 0.005, 0.42, 0.095])
    all_fvt_axes = axes_fvt + [ax_bfvt0, ax_bfvt1]

    _check_health(df)
    _check_class_balance(df, ax_balance)
    _plot_distributions(df, axes_cont, axes_bin)
    _plot_correlations(df, ax_pearson, ax_spearman)
    _plot_feature_vs_target(df, all_fvt_axes)
    _print_summary()

    fig.savefig(save_path, dpi=150, bbox_inches="tight")
    print(f"  Figure saved → {save_path}\n")
    plt.show()


# ─── Synthetic data generator (for standalone smoke-test) ─────────────────────
def _make_synthetic_df(n: int = 5_000, seed: int = 42) -> pd.DataFrame:
    """
    Class distribution mimics a realistic financial platform:
      0 (ignore):    60%   1 (search): 18%   2 (watchlist): 10%
      3 (view):       8%   4 (order):   4%
    Features have weak class-conditional signal so ANOVA/chi-sq should fire correctly.
    """
    rng = np.random.default_rng(seed)
    targets = rng.choice([0, 1, 2, 3, 4], size=n, p=[0.60, 0.18, 0.10, 0.08, 0.04])

    return pd.DataFrame({
        "current_interest_score": np.clip(
            0.1 + targets * 0.15 + rng.normal(0, 0.12, n), 0, 1),
        "time_since_last_interaction": np.clip(
            rng.exponential(scale=60 - targets * 10, size=n), 0, 500),
        "is_active_trader": (rng.random(n) < 0.2 + targets * 0.1).astype(int),
        "historical_conversion_rate": np.clip(
            rng.beta(2 + targets * 0.5, 8 - targets * 0.3, size=n), 0, 1),
        "asset_price_change_24h": rng.normal(
            loc=targets * 0.3 - 0.5, scale=2.5, size=n),
        "asset_trading_volume_spike": (
            rng.random(n) < 0.1 + targets * 0.08).astype(int),
        TARGET: targets,
    })


if __name__ == "__main__":
    print("Running EDA on SYNTHETIC data (replace df_train with your real DataFrame).")
    df_train = _make_synthetic_df(n=10_000)
    run_eda(df_train)
```

---

## Part B — "Is This Data Good Enough?" Evaluation Checklist

### 1. Red Flags: Data Leakage & Bad Distributions

| Signal | Threshold | What it means |
|---|---|---|
| Feature–target Pearson or Spearman \|r\| > **0.90** | FAIL | Almost certain leakage. `current_interest_score` > 0.90 with target is the most dangerous — it may have been computed using the event itself. |
| Feature–feature \|r\| > **0.85** | WARN | Multicollinearity. Run VIF; drop the weaker feature. |
| \|Skewness\| > **2.0** for a continuous feature | WARN | Extreme skew compresses the feature's signal. Apply `log1p` (if right-skewed) or `Box-Cox`. |
| Any column with **> 20% NaN** | FAIL | Imputation at that rate distorts the distribution; investigate the data pipeline. |
| Infinite values in any column | FAIL | XGBoost silently propagates NaN from inf; will produce garbage splits. |
| A feature has **zero variance** (all values identical) | FAIL | Dead feature — the DE pipeline likely has a bug (e.g., a `GROUP BY` that collapsed everything to the same value). |

**Most dangerous leakage pattern for this schema:** `current_interest_score` is computed as a rolling
aggregate of a user's event history. If the JOIN window is not strictly `< event_timestamp`, the score
will have seen the target event itself, inflating its correlation to near 1.0.

---

### 2. Class Imbalance — Intervention Thresholds

| Imbalance Ratio (max/min) | Recommended Strategy |
|---|---|
| < 5× | No action needed. Vanilla XGBoost with default settings. |
| 5× – 20× | Set `sample_weight` per row. XGBoost's `scale_pos_weight` is a scalar and does not apply cleanly to multi-class — use the sklearn wrapper with `class_weight="balanced"` instead. |
| > 20× | SMOTE on the minority class(es) before training + stratified k-fold CV. |

**For multi-class specifically:** compute per-row weights as
`n_samples / (n_classes × class_counts[y_i])` and pass to `fit(sample_weight=...)`.

A ratio of **60:4 (ignore vs order) = 15×** is the realistic worst-case for this platform.
That lands in the WARN zone — weighted sampling is sufficient; SMOTE is optional.

---

### 3. Point-in-Time Correctness — Manual Verification Checklist

These cannot be caught by statistical tests alone. Verify by inspecting the DE team's SQL JOIN logic:

- [ ] **`current_interest_score`** — rolling window must use `WHERE event_ts < target_event_ts` (strict less-than, not `<=`).
- [ ] **`asset_price_change_24h`** — must be pulled from `market_snapshot_history` at the closest `snapshot_at <= event_ts`, NOT from the live `market_snapshot` table.
- [ ] **`time_since_last_interaction`** — delta must be `target_event_ts − prior_event_ts`, not `now() − prior_event_ts`. Using `now()` at feature-generation time makes this feature non-reproducible and leaky.
- [ ] **`historical_conversion_rate`** — defined as `COUNT(DISTINCT stocks bought) / COUNT(DISTINCT stocks viewed)` over `[event_ts − 90d, event_ts)`. Source: `behavioral_events` where `event_metric_name IN ('order-created', 'ticker-view')`. Must exclude the current event from the window.
- [ ] **`asset_trading_volume_spike`** — the `avg_30d_volume` baseline must come from `market_snapshot_history` snapshots before the event date, not the live table.
- [ ] **Train/test split** — must be temporal (`df[df.event_ts < cutoff]` for train), not random. A random split leaks future events into training.

---

## Verification

```bash
# Smoke-test on synthetic data
python eda_propensity.py
# → all 6 sections complete, eda_report.png written

# Inject known failures to confirm flag logic:
# 1. Leakage:  df['current_interest_score'] = df['target_action'] * 0.25  → ❌ FAIL
# 2. NaN:      df.loc[:100, 'historical_conversion_rate'] = np.nan         → ⚠️  WARN
# 3. Imbalance: add class with 0.5% frequency                              → ❌ FAIL
```
