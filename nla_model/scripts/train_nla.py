"""
train_nla.py
============
Train the XGBoost NLA Propensity Model with BorderlineSMOTE resampling.

Steps:
  1. Load df_train from tmp/df_train_real.csv
  2. Apply log1p to skewed features
  3. BorderlineSMOTE on minority classes (1, 2, 4) → ~1 300 samples each
  4. StratifiedKFold(k=5) cross-validation
  5. Train final model on full resampled data
  6. Save model → tmp/nla_model.json
  7. Print feature importances + per-class CV metrics

Usage:
    python train_nla.py
"""

import os
import json
import numpy as np
import pandas as pd
from imblearn.over_sampling import BorderlineSMOTE
from sklearn.model_selection import StratifiedKFold
from sklearn.metrics import classification_report, confusion_matrix
from sklearn.preprocessing import LabelEncoder
import xgboost as xgb

OUTPUT_DIR = os.path.join(os.path.dirname(__file__), "..", "output")
DATA_PATH  = os.path.join(OUTPUT_DIR, "df_train_real.csv")
MODEL_PATH = os.path.join(OUTPUT_DIR, "nla_model.json")

TARGET = "target_action"
LOG1P_FEATURES = ["time_since_last_interaction", "historical_conversion_rate"]
FEATURES = [
    "current_interest_score",
    "time_since_last_interaction",
    "is_active_trader",
    "historical_conversion_rate",
    "asset_price_change_24h",
    "asset_trading_volume_spike",
]
TARGET_LABELS = {0: "ignore", 1: "search", 2: "watchlist", 3: "view", 4: "order"}
SMOTE_TARGET  = {1: 1300, 2: 1300, 4: 1300}
N_SPLITS      = 5
RANDOM_STATE  = 42
N_EST_CV      = 100   # fast estimator count for CV scoring
N_EST_FINAL   = 400   # full estimator count for the saved model


def load_and_transform(path: str) -> tuple[pd.DataFrame, pd.Series]:
    df = pd.read_csv(path)
    print(f"Loaded {len(df):,} rows from {path}")

    for col in LOG1P_FEATURES:
        df[col] = np.log1p(df[col])
    print(f"log1p applied to: {LOG1P_FEATURES}")

    X = df[FEATURES]
    y = df[TARGET]
    print(f"\nClass distribution (raw):")
    for cls, cnt in y.value_counts().sort_index().items():
        print(f"  {cls} ({TARGET_LABELS[cls]}): {cnt:,}  ({cnt/len(y):.1%})")

    return X, y


def apply_smote(X: pd.DataFrame, y: pd.Series):
    smote = BorderlineSMOTE(sampling_strategy=SMOTE_TARGET, random_state=RANDOM_STATE)
    X_res, y_res = smote.fit_resample(X, y)

    print(f"\nClass distribution (after SMOTE):")
    unique, counts = np.unique(y_res, return_counts=True)
    for cls, cnt in zip(unique, counts):
        print(f"  {cls} ({TARGET_LABELS[cls]}): {cnt:,}  ({cnt/len(y_res):.1%})")
    print(f"  Total: {len(y_res):,} rows")

    return X_res, y_res


def build_model(n_estimators: int = N_EST_FINAL) -> xgb.XGBClassifier:
    return xgb.XGBClassifier(
        objective="multi:softprob",
        num_class=5,
        n_estimators=n_estimators,
        max_depth=6,
        learning_rate=0.05,
        subsample=0.8,
        colsample_bytree=0.8,
        eval_metric="mlogloss",
        random_state=RANDOM_STATE,
        n_jobs=-1,
    )


def cross_validate(X_res, y_res) -> None:
    print(f"\n{'='*60}")
    print(f"STRATIFIED K-FOLD CV  (k={N_SPLITS})")
    print("=" * 60)

    skf = StratifiedKFold(n_splits=N_SPLITS, shuffle=True, random_state=RANDOM_STATE)
    fold_reports = []

    for fold, (train_idx, val_idx) in enumerate(skf.split(X_res, y_res), 1):
        X_tr, X_val = X_res[train_idx], X_res[val_idx]
        y_tr, y_val = y_res[train_idx], y_res[val_idx]

        model = build_model(n_estimators=N_EST_CV)
        model.fit(X_tr, y_tr, verbose=False)
        y_pred = model.predict(X_val)

        report = classification_report(
            y_val, y_pred,
            target_names=[TARGET_LABELS[i] for i in range(5)],
            output_dict=True,
        )
        fold_reports.append(report)
        print(f"\n  Fold {fold}:")
        print(classification_report(
            y_val, y_pred,
            target_names=[TARGET_LABELS[i] for i in range(5)],
        ))

    # Average macro F1 across folds
    macro_f1s = [r["macro avg"]["f1-score"] for r in fold_reports]
    print(f"\n  Mean macro-F1: {np.mean(macro_f1s):.4f} ± {np.std(macro_f1s):.4f}")


def train_final(X_res, y_res) -> xgb.XGBClassifier:
    print(f"\n{'='*60}")
    print("FINAL MODEL (full resampled data)")
    print("=" * 60)

    model = build_model()
    model.fit(X_res, y_res, verbose=False)

    importances = dict(zip(FEATURES, model.feature_importances_))
    print("\n  Feature importances (gain):")
    for feat, imp in sorted(importances.items(), key=lambda x: -x[1]):
        print(f"    {feat:<40} {imp:.4f}")

    return model


def main():
    os.makedirs(OUTPUT_DIR, exist_ok=True)

    X, y = load_and_transform(DATA_PATH)
    X_res, y_res = apply_smote(X.values, y.values)

    cross_validate(X_res, y_res)

    model = train_final(X_res, y_res)
    model.save_model(MODEL_PATH)
    print(f"\nModel saved → {MODEL_PATH}")


if __name__ == "__main__":
    main()
