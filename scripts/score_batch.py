from __future__ import annotations

import argparse
import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.model_backend import FEATURE_COLUMNS, LocalModelBackend


def main() -> None:
    parser = argparse.ArgumentParser(description="Score batch local para el caso Customer Churn.")
    parser.add_argument("--input", default=ROOT / "data" / "fixtures" / "batch-input.csv", type=Path)
    parser.add_argument("--model", default=ROOT / "models" / "churn-baseline.joblib", type=Path)
    parser.add_argument("--output", default=ROOT / "data" / "scored" / "batch-scored.csv", type=Path)
    parser.add_argument("--top", default=10, type=int)
    args = parser.parse_args()

    frame = pd.read_csv(args.input)
    missing = set(FEATURE_COLUMNS) - set(frame.columns)
    if missing:
        raise ValueError(f"Faltan columnas para scorear: {sorted(missing)}")

    backend = LocalModelBackend(args.model)
    scored = frame.copy()
    scored["churn_probability"] = [
        backend.predict_one(row[FEATURE_COLUMNS].to_dict()).churn_probability for _, row in scored.iterrows()
    ]
    scored["churn_prediction"] = scored["churn_probability"] >= 0.7
    scored["priority_score"] = scored["churn_probability"] * scored["MonthlyCharges"]
    scored = scored.sort_values("priority_score", ascending=False)

    args.output.parent.mkdir(parents=True, exist_ok=True)
    scored.to_csv(args.output, index=False)
    print(f"Batch score guardado en {args.output}")
    print(scored[["customerID", "churn_probability", "MonthlyCharges", "priority_score"]].head(args.top).to_string(index=False))


if __name__ == "__main__":
    main()
