from __future__ import annotations

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from ml.public_benchmark_slabs import (
    DATASET_NAME,
    THRESHOLDS,
    load_public_dataset,
    metrics_from_predictions,
    predictions_from_probabilities,
    print_errors,
    print_metrics,
    regex_predictions,
    select_threshold,
    to_rows,
)
from ml.train_and_compare import build_model


def normalize_text(text: str) -> str:
    return " ".join(text.strip().lower().split())


def remove_exact_overlaps(
    rows: list[dict],
    blocked_texts: set[str],
) -> tuple[list[dict], int]:
    cleaned = []
    removed = 0

    for row in rows:
        normalized = normalize_text(row["text"])
        if normalized in blocked_texts:
            removed += 1
            continue

        cleaned.append(row)

    return cleaned, removed


def normalized_texts(rows: list[dict]) -> set[str]:
    return {
        normalize_text(row["text"])
        for row in rows
    }


def main() -> None:
    dataset = load_public_dataset()

    train_rows = to_rows(dataset["train"])
    validation_rows = to_rows(dataset["validation"])
    test_rows = to_rows(dataset["test"])

    train_texts = normalized_texts(train_rows)

    validation_clean, removed_train_val = remove_exact_overlaps(
        validation_rows,
        train_texts,
    )

    validation_texts = normalized_texts(validation_clean)

    test_without_train, removed_train_test = remove_exact_overlaps(
        test_rows,
        train_texts,
    )

    test_clean, removed_val_test = remove_exact_overlaps(
        test_without_train,
        validation_texts,
    )

    print(f"Dataset: {DATASET_NAME}")
    print()
    print("Leakage cleanup")
    print("-" * 90)
    print(
        f"Validation: {len(validation_rows)} -> {len(validation_clean)} "
        f"(removed train overlap: {removed_train_val})"
    )
    print(
        f"Test:       {len(test_rows)} -> {len(test_clean)} "
        f"(removed train overlap: {removed_train_test}, "
        f"validation overlap: {removed_val_test})"
    )
    print()

    model = build_model()
    model.fit(
        [row["text"] for row in train_rows],
        [1 if row["label"] == "attack" else 0 for row in train_rows],
    )

    validation_probabilities = model.predict_proba(
        [row["text"] for row in validation_clean]
    )[:, 1]

    test_probabilities = model.predict_proba(
        [row["text"] for row in test_clean]
    )[:, 1]

    validation_regex = regex_predictions(validation_clean)
    test_regex = regex_predictions(test_clean)

    ml_threshold, ml_validation_metrics = select_threshold(
        validation_clean,
        validation_probabilities,
    )

    hybrid_threshold, hybrid_validation_metrics = select_threshold(
        validation_clean,
        validation_probabilities,
        regex_preds=validation_regex,
    )

    print("Threshold selection — CLEAN VALIDATION ONLY")
    print("-" * 90)
    print(f"ML-only threshold: {ml_threshold:.2f}")
    print_metrics("ML validation", ml_validation_metrics)
    print()
    print(f"Hybrid threshold:  {hybrid_threshold:.2f}")
    print_metrics("Hybrid val", hybrid_validation_metrics)
    print()

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
        test_clean,
        test_regex,
    )
    ml_metrics = metrics_from_predictions(
        test_clean,
        test_ml,
    )
    hybrid_metrics = metrics_from_predictions(
        test_clean,
        test_hybrid,
    )

    print("CLEAN TEST RESULTS")
    print("=" * 90)
    print_metrics("Regex only", regex_metrics)
    print_metrics("ML only", ml_metrics)
    print_metrics("Hybrid", hybrid_metrics)
    print()

    print_errors(
        "ML clean-test errors",
        test_clean,
        test_ml,
        test_probabilities,
    )
    print_errors(
        "Hybrid clean-test errors",
        test_clean,
        test_hybrid,
        test_probabilities,
    )

    print(
        "Methodology note: exact duplicates are removed from validation "
        "against train, and from test against both train and cleaned validation "
        "before threshold selection and final evaluation."
    )


if __name__ == "__main__":
    main()
