from __future__ import annotations

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.guards.input.rule_guard import RuleGuard
from app.policies.input_policy import InputPolicy, PolicyAction
from ml.train_and_compare import (
    TEST_PATH,
    TRAIN_PATH,
    build_model,
    load_jsonl,
    metrics_from_predictions,
)


THRESHOLDS = (0.40, 0.45, 0.50, 0.55, 0.60, 0.65, 0.70, 0.75, 0.80)


def print_metrics(name: str, threshold: float, metrics) -> None:
    print(
        f"{name:<10} "
        f"thr={threshold:.2f}  "
        f"P={metrics.precision:.3f}  "
        f"R={metrics.recall:.3f}  "
        f"F1={metrics.f1:.3f}  "
        f"FPR={metrics.false_positive_rate:.3f}  "
        f"FNR={metrics.false_negative_rate:.3f}"
    )


def main() -> None:
    train_rows = load_jsonl(TRAIN_PATH)
    test_rows = load_jsonl(TEST_PATH)

    model = build_model()
    model.fit(
        [row["text"] for row in train_rows],
        [1 if row["label"] == "attack" else 0 for row in train_rows],
    )

    probabilities = model.predict_proba(
        [row["text"] for row in test_rows]
    )[:, 1]

    guard = RuleGuard()
    policy = InputPolicy()

    regex_predictions = []
    for row in test_rows:
        result = guard.analyze(row["text"])
        decision = policy.decide(result.score)
        regex_predictions.append(
            decision.action == PolicyAction.BLOCK
        )

    print(
        f"Training set: {len(train_rows)} | "
        f"Evaluation set: {len(test_rows)}"
    )
    print()
    print("ML threshold sweep")
    print("-" * 88)

    sweep_rows = []

    for threshold in THRESHOLDS:
        ml_predictions = [
            probability >= threshold
            for probability in probabilities
        ]

        hybrid_predictions = [
            regex_attack or ml_attack
            for regex_attack, ml_attack in zip(
                regex_predictions,
                ml_predictions,
            )
        ]

        ml_metrics = metrics_from_predictions(test_rows, ml_predictions)
        hybrid_metrics = metrics_from_predictions(test_rows, hybrid_predictions)

        sweep_rows.append(
            (
                threshold,
                ml_metrics,
                hybrid_metrics,
                ml_predictions,
                hybrid_predictions,
            )
        )

        print_metrics("ML", threshold, ml_metrics)
        print_metrics("Hybrid", threshold, hybrid_metrics)
        print()

    candidate = max(
        sweep_rows,
        key=lambda item: (
            item[2].f1,
            -item[2].false_positive_rate,
            item[2].recall,
        ),
    )

    (
        best_threshold,
        best_ml_metrics,
        best_hybrid_metrics,
        best_ml_predictions,
        best_hybrid_predictions,
    ) = candidate

    print("Experimental candidate on this synthetic evaluation set")
    print("-" * 88)
    print_metrics("ML", best_threshold, best_ml_metrics)
    print_metrics("Hybrid", best_threshold, best_hybrid_metrics)
    print()

    ml_false_positives = []
    ml_false_negatives = []

    for row, prediction, probability in zip(
        test_rows,
        best_ml_predictions,
        probabilities,
    ):
        actual_attack = row["label"] == "attack"
        if not actual_attack and prediction:
            ml_false_positives.append((row, probability))
        elif actual_attack and not prediction:
            ml_false_negatives.append((row, probability))

    print(f"ML false positives @ {best_threshold:.2f}: {len(ml_false_positives)}")
    print("-" * 88)
    for row, probability in ml_false_positives:
        print(f'{row["id"]} | ml={probability:.3f} | {row["text"]}')
    print()

    print(f"ML false negatives @ {best_threshold:.2f}: {len(ml_false_negatives)}")
    print("-" * 88)
    for row, probability in ml_false_negatives:
        print(f'{row["id"]} | ml={probability:.3f} | {row["text"]}')
    print()

    hybrid_false_positives = []
    hybrid_false_negatives = []

    for row, prediction in zip(test_rows, best_hybrid_predictions):
        actual_attack = row["label"] == "attack"
        if not actual_attack and prediction:
            hybrid_false_positives.append(row)
        elif actual_attack and not prediction:
            hybrid_false_negatives.append(row)

    print(
        f"Hybrid false positives @ {best_threshold:.2f}: "
        f"{len(hybrid_false_positives)}"
    )
    print(
        f"Hybrid false negatives @ {best_threshold:.2f}: "
        f"{len(hybrid_false_negatives)}"
    )
    print()

    print(
        "Important: this threshold is only an experimental candidate because "
        "both train and evaluation data are synthetic."
    )


if __name__ == "__main__":
    main()
