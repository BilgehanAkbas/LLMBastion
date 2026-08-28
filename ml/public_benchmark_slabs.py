from __future__ import annotations

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.guards.input.rule_guard import RuleGuard
from app.policies.input_policy import InputPolicy, PolicyAction
from ml.train_and_compare import build_model, metrics_from_predictions


DATASET_NAME = "S-Labs/prompt-injection-dataset"
THRESHOLDS = (
    0.30,
    0.35,
    0.40,
    0.45,
    0.50,
    0.55,
    0.60,
    0.65,
    0.70,
    0.75,
    0.80,
)


def load_public_dataset():
    try:
        from datasets import load_dataset
    except ImportError as exc:
        raise RuntimeError(
            "Missing dependency: datasets. Run: pip install datasets"
        ) from exc

    return load_dataset(DATASET_NAME)


def to_rows(split) -> list[dict]:
    rows = []
    for index, item in enumerate(split):
        label = int(item["label"])
        if label not in (0, 1):
            raise ValueError(f"Unexpected label at row {index}: {label}")

        rows.append(
            {
                "id": f"row-{index + 1:05d}",
                "text": str(item["text"]),
                "label": "attack" if label == 1 else "safe",
            }
        )
    return rows


def normalized_texts(rows: list[dict]) -> set[str]:
    return {
        row["text"].strip().lower()
        for row in rows
    }


def regex_predictions(rows: list[dict]) -> list[bool]:
    guard = RuleGuard()
    policy = InputPolicy()

    predictions = []
    for row in rows:
        result = guard.analyze(row["text"])
        decision = policy.decide(result.score)
        predictions.append(
            decision.action == PolicyAction.BLOCK
        )
    return predictions


def predictions_from_probabilities(
    probabilities,
    threshold: float,
) -> list[bool]:
    return [
        probability >= threshold
        for probability in probabilities
    ]


def select_threshold(
    rows: list[dict],
    probabilities,
    *,
    regex_preds: list[bool] | None = None,
) -> tuple[float, object]:
    candidates = []

    for threshold in THRESHOLDS:
        ml_preds = predictions_from_probabilities(
            probabilities,
            threshold,
        )

        if regex_preds is None:
            predictions = ml_preds
        else:
            predictions = [
                regex_attack or ml_attack
                for regex_attack, ml_attack in zip(
                    regex_preds,
                    ml_preds,
                )
            ]

        metrics = metrics_from_predictions(
            rows,
            predictions,
        )

        candidates.append(
            (threshold, metrics)
        )

    # Primary goal: F1.
    # Ties: lower false-positive rate, then higher recall.
    return max(
        candidates,
        key=lambda item: (
            item[1].f1,
            -item[1].false_positive_rate,
            item[1].recall,
        ),
    )


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


def print_errors(
    title: str,
    rows: list[dict],
    predictions: list[bool],
    probabilities=None,
    limit: int = 10,
) -> None:
    errors = []

    for index, (row, predicted_attack) in enumerate(
        zip(rows, predictions)
    ):
        actual_attack = row["label"] == "attack"

        if actual_attack == predicted_attack:
            continue

        probability = (
            None
            if probabilities is None
            else float(probabilities[index])
        )

        errors.append(
            (row, predicted_attack, probability)
        )

    print(f"{title}: {len(errors)}")
    print("-" * 90)

    for row, predicted_attack, probability in errors[:limit]:
        outcome = (
            "FP"
            if row["label"] == "safe"
            else "FN"
        )
        probability_text = (
            ""
            if probability is None
            else f" ml={probability:.3f}"
        )
        print(
            f'{outcome} |{probability_text} | '
            f'{row["text"]}'
        )

    if len(errors) > limit:
        print(f"... {len(errors) - limit} more")

    print()


def main() -> None:
    dataset = load_public_dataset()

    train_rows = to_rows(dataset["train"])
    validation_rows = to_rows(dataset["validation"])
    test_rows = to_rows(dataset["test"])

    train_texts = normalized_texts(train_rows)
    validation_texts = normalized_texts(validation_rows)
    test_texts = normalized_texts(test_rows)

    train_validation_overlap = train_texts & validation_texts
    train_test_overlap = train_texts & test_texts
    validation_test_overlap = validation_texts & test_texts

    print(f"Dataset: {DATASET_NAME}")
    print(
        f"Train:      {len(train_rows)} | "
        f"safe={sum(r['label'] == 'safe' for r in train_rows)} | "
        f"attack={sum(r['label'] == 'attack' for r in train_rows)}"
    )
    print(
        f"Validation: {len(validation_rows)} | "
        f"safe={sum(r['label'] == 'safe' for r in validation_rows)} | "
        f"attack={sum(r['label'] == 'attack' for r in validation_rows)}"
    )
    print(
        f"Test:       {len(test_rows)} | "
        f"safe={sum(r['label'] == 'safe' for r in test_rows)} | "
        f"attack={sum(r['label'] == 'attack' for r in test_rows)}"
    )
    print()
    print(
        "Exact overlap | "
        f"train/val={len(train_validation_overlap)} | "
        f"train/test={len(train_test_overlap)} | "
        f"val/test={len(validation_test_overlap)}"
    )
    print()

    model = build_model()
    model.fit(
        [row["text"] for row in train_rows],
        [1 if row["label"] == "attack" else 0 for row in train_rows],
    )

    validation_probabilities = model.predict_proba(
        [row["text"] for row in validation_rows]
    )[:, 1]

    test_probabilities = model.predict_proba(
        [row["text"] for row in test_rows]
    )[:, 1]

    validation_regex = regex_predictions(validation_rows)
    test_regex = regex_predictions(test_rows)

    ml_threshold, ml_validation_metrics = select_threshold(
        validation_rows,
        validation_probabilities,
    )

    hybrid_threshold, hybrid_validation_metrics = select_threshold(
        validation_rows,
        validation_probabilities,
        regex_preds=validation_regex,
    )

    print("Threshold selection — VALIDATION ONLY")
    print("-" * 90)
    print(
        f"ML-only threshold: {ml_threshold:.2f}"
    )
    print_metrics("ML validation", ml_validation_metrics)
    print()
    print(
        f"Hybrid threshold:  {hybrid_threshold:.2f}"
    )
    print_metrics(
        "Hybrid val",
        hybrid_validation_metrics,
    )
    print()

    # Test is evaluated only after thresholds are selected.
    test_ml = predictions_from_probabilities(
        test_probabilities,
        ml_threshold,
    )

    test_hybrid_ml = predictions_from_probabilities(
        test_probabilities,
        hybrid_threshold,
    )
    test_hybrid = [
        regex_attack or ml_attack
        for regex_attack, ml_attack in zip(
            test_regex,
            test_hybrid_ml,
        )
    ]

    regex_metrics = metrics_from_predictions(
        test_rows,
        test_regex,
    )
    ml_metrics = metrics_from_predictions(
        test_rows,
        test_ml,
    )
    hybrid_metrics = metrics_from_predictions(
        test_rows,
        test_hybrid,
    )

    print("FINAL TEST RESULTS")
    print("=" * 90)
    print_metrics("Regex only", regex_metrics)
    print_metrics("ML only", ml_metrics)
    print_metrics("Hybrid", hybrid_metrics)
    print()

    print_errors(
        "ML test errors",
        test_rows,
        test_ml,
        test_probabilities,
    )
    print_errors(
        "Hybrid test errors",
        test_rows,
        test_hybrid,
        test_probabilities,
    )

    print(
        "Methodology note: model training uses only the train split. "
        "Thresholds are selected only on validation. "
        "The test split is not used for fitting or threshold selection."
    )


if __name__ == "__main__":
    main()
