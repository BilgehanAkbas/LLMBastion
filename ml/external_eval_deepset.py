from __future__ import annotations

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.guards.input.rule_guard import RuleGuard
from app.policies.input_policy import InputPolicy, PolicyAction
from ml.train_and_compare import (
    TRAIN_PATH,
    build_model,
    load_jsonl,
    metrics_from_predictions,
)


EXTERNAL_DATASET = "deepset/prompt-injections"
EXTERNAL_SPLIT = "test"
ML_THRESHOLD = 0.60


def load_external_rows() -> list[dict]:
    try:
        from datasets import load_dataset
    except ImportError as exc:
        raise RuntimeError(
            "Missing dependency: datasets. Run: pip install datasets"
        ) from exc

    dataset = load_dataset(EXTERNAL_DATASET, split=EXTERNAL_SPLIT)

    rows = []
    for index, item in enumerate(dataset):
        text = str(item["text"])
        label = int(item["label"])

        if label not in (0, 1):
            raise ValueError(f"Unexpected external label at row {index}: {label}")

        rows.append(
            {
                "id": f"external-{index + 1:03d}",
                "text": text,
                "label": "attack" if label == 1 else "safe",
            }
        )

    return rows


def print_metrics(name: str, metrics) -> None:
    print(
        f"{name:<14} "
        f"P={metrics.precision:.3f}  "
        f"R={metrics.recall:.3f}  "
        f"F1={metrics.f1:.3f}  "
        f"Acc={metrics.accuracy:.3f}  "
        f"FPR={metrics.false_positive_rate:.3f}  "
        f"FNR={metrics.false_negative_rate:.3f}"
    )
    print(
        f"{'':14} "
        f"TP={metrics.tp} FP={metrics.fp} "
        f"TN={metrics.tn} FN={metrics.fn}"
    )


def main() -> None:
    train_rows = load_jsonl(TRAIN_PATH)
    external_rows = load_external_rows()

    train_texts = {row["text"].strip().lower() for row in train_rows}
    external_texts = {row["text"].strip().lower() for row in external_rows}
    exact_overlap = train_texts & external_texts

    print(f"External dataset: {EXTERNAL_DATASET}")
    print(f"Split:            {EXTERNAL_SPLIT}")
    print(f"Rows:             {len(external_rows)}")
    print(
        "Labels:           "
        f"{sum(row['label'] == 'safe' for row in external_rows)} safe / "
        f"{sum(row['label'] == 'attack' for row in external_rows)} attack"
    )
    print(f"Exact train overlap: {len(exact_overlap)}")
    print(f"Fixed ML threshold: {ML_THRESHOLD:.2f}")
    print()

    if exact_overlap:
        print(
            "WARNING: exact text overlap exists between the synthetic "
            "training set and external benchmark."
        )
        print()

    model = build_model()
    model.fit(
        [row["text"] for row in train_rows],
        [1 if row["label"] == "attack" else 0 for row in train_rows],
    )

    probabilities = model.predict_proba(
        [row["text"] for row in external_rows]
    )[:, 1]

    ml_predictions = [
        probability >= ML_THRESHOLD for probability in probabilities
    ]

    guard = RuleGuard()
    policy = InputPolicy()
    regex_predictions = []

    for row in external_rows:
        result = guard.analyze(row["text"])
        decision = policy.decide(result.score)
        regex_predictions.append(decision.action == PolicyAction.BLOCK)

    hybrid_predictions = [
        regex_attack or ml_attack
        for regex_attack, ml_attack in zip(regex_predictions, ml_predictions)
    ]

    regex_metrics = metrics_from_predictions(external_rows, regex_predictions)
    ml_metrics = metrics_from_predictions(external_rows, ml_predictions)
    hybrid_metrics = metrics_from_predictions(external_rows, hybrid_predictions)

    print("External benchmark results")
    print("-" * 86)
    print_metrics("Regex only", regex_metrics)
    print_metrics("ML only", ml_metrics)
    print_metrics("Hybrid OR", hybrid_metrics)
    print()

    print(
        "Methodology note: ML threshold=0.60 was selected BEFORE running "
        "this external benchmark. Do not retune it on this dataset if you "
        "want to preserve this result as a held-out check."
    )


if __name__ == "__main__":
    main()
