"""
Generate synthetic edge flow data for congestion forecasting.

Outputs:
- data/flows.csv : base dataset with lag features
- data/flows_train.csv, data/flows_val.csv, data/flows_test.csv : simple time splits

Assumptions:
- Edges come from data/edges.csv with length_m and capacity.
- Time steps are 15-minute intervals over 7 days.
- Demand peaks around class-change windows.
"""

import csv
from pathlib import Path

import numpy as np
import pandas as pd

DATA_DIR = Path("data")
EDGES_CSV = DATA_DIR / "edges.csv"
FLOWS_CSV = DATA_DIR / "flows.csv"

# 15-minute intervals over 7 days
INTERVAL_MINUTES = 15
DAYS = 7
POINTS_PER_DAY = (24 * 60) // INTERVAL_MINUTES

# Peak hours (approximate class changes)
PEAK_HOURS = [8, 9, 10, 13, 14, 15, 16]


def load_edges():
    edges = []
    with EDGES_CSV.open(newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            edges.append(row)
    return edges


def generate_base_flow(capacity, hour, is_peak):
    base = 0.25 * capacity
    if is_peak:
        base += 0.4 * capacity
    else:
        # mild off-peak usage
        base += 0.1 * capacity
    # add hour trend (morning < afternoon)
    base += 0.05 * capacity * (hour / 24)
    return base


def build_dataset():
    edges = load_edges()
    rows = []
    rng = np.random.default_rng(42)
    total_steps = POINTS_PER_DAY * DAYS

    for edge in edges:
        cap = float(edge["capacity"])
        length = float(edge["length_m"])
        edge_id = edge["id"]
        for t in range(total_steps):
            day = t // POINTS_PER_DAY
            day_of_week = day % 7
            idx_in_day = t % POINTS_PER_DAY
            hour = (idx_in_day * INTERVAL_MINUTES) / 60
            is_peak = int(int(hour) in PEAK_HOURS)

            mean_flow = generate_base_flow(cap, hour, is_peak)
            noise = rng.normal(0, 0.08 * cap)
            flow = max(0.0, mean_flow + noise)

            rows.append(
                {
                    "edge_id": edge_id,
                    "t": t,
                    "day": day,
                    "day_of_week": day_of_week,
                    "hour": hour,
                    "is_peak": is_peak,
                    "capacity": cap,
                    "length_m": length,
                    "flow": flow,
                }
            )

    df = pd.DataFrame(rows)
    # Lag features per edge
    df["flow_lag1"] = df.groupby("edge_id")["flow"].shift(1)
    df["flow_lag2"] = df.groupby("edge_id")["flow"].shift(2)
    # Congestion class: low/med/high by capacity ratio
    ratio = df["flow"] / df["capacity"].clip(lower=1)
    df["congestion_class"] = pd.cut(
        ratio,
        bins=[-np.inf, 0.5, 0.8, np.inf],
        labels=["low", "med", "high"],
    )
    df = df.dropna().reset_index(drop=True)
    return df


def split_time_series(df: pd.DataFrame):
    # simple time-based split: 5 days train, 1 day val, 1 day test
    max_day = df["day"].max()
    train_df = df[df["day"] <= 4]
    val_df = df[df["day"] == 5]
    test_df = df[df["day"] == 6]
    return train_df, val_df, test_df


def main():
    df = build_dataset()
    FLOWS_CSV.parent.mkdir(exist_ok=True)
    df.to_csv(FLOWS_CSV, index=False)
    train_df, val_df, test_df = split_time_series(df)
    train_df.to_csv(DATA_DIR / "flows_train.csv", index=False)
    val_df.to_csv(DATA_DIR / "flows_val.csv", index=False)
    test_df.to_csv(DATA_DIR / "flows_test.csv", index=False)
    print(
        f"Saved flows: base={len(df)}, train={len(train_df)}, val={len(val_df)}, test={len(test_df)}"
    )


if __name__ == "__main__":
    main()
