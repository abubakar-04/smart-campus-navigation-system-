"""
Train a RandomForestRegressor baseline to predict next-interval flow.

Inputs:
- data/flows_train.csv, data/flows_val.csv (from generate_synthetic_flows.py)

Outputs:
- models/rf_flow.pkl : trained RandomForestRegressor
- data/metrics_rf.json : validation metrics (RMSE, MAE)
"""

import json
from pathlib import Path

import joblib
import numpy as np
import pandas as pd
from sklearn.ensemble import RandomForestRegressor
from sklearn.metrics import mean_absolute_error, mean_squared_error

DATA_DIR = Path("data")
MODELS_DIR = Path("models")

FEATURES = [
    "hour",
    "day_of_week",
    "is_peak",
    "capacity",
    "length_m",
    "flow_lag1",
    "flow_lag2",
]
TARGET = "flow"


def load_splits():
    train_df = pd.read_csv(DATA_DIR / "flows_train.csv")
    val_df = pd.read_csv(DATA_DIR / "flows_val.csv")
    return train_df, val_df


def prepare_xy(df: pd.DataFrame):
    X = df[FEATURES].copy()
    y = df[TARGET].copy()
    X = X.fillna(0.0)
    return X, y


def main():
    train_df, val_df = load_splits()
    X_train, y_train = prepare_xy(train_df)
    X_val, y_val = prepare_xy(val_df)

    model = RandomForestRegressor(
        n_estimators=200,
        max_depth=None,
        min_samples_leaf=1,
        n_jobs=-1,
        random_state=42,
    )
    model.fit(X_train, y_train)

    val_pred = model.predict(X_val)
    rmse = float(np.sqrt(mean_squared_error(y_val, val_pred)))
    mae = float(mean_absolute_error(y_val, val_pred))

    MODELS_DIR.mkdir(exist_ok=True)
    joblib.dump(model, MODELS_DIR / "rf_flow.pkl")

    metrics = {"rmse_val": rmse, "mae_val": mae}
    (DATA_DIR / "metrics_rf.json").write_text(json.dumps(metrics, indent=2))

    print(f"Trained RF model. Val RMSE={rmse:.2f}, MAE={mae:.2f}")


if __name__ == "__main__":
    main()
