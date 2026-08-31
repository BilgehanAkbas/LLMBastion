from __future__ import annotations

import sys
from collections import defaultdict
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from datasets import load_dataset

from app.guards.input.rule_guard import RuleGuard
from app.guards.input.semantic_guard import SemanticGuard
from app.policies.input_policy import InputPolicy, PolicyAction
from ml.train_and_compare import metrics_from_predictions


DATASET_NAME = "3nesdeniz/turkish-conversation-prompt-injection"
SEMANTIC_THRESHOLD = 0.40


def to_rows(split) -> list[dict]:
    rows = []
    for item in split:
        rows.append(
            {
                "id": str(item["id"]),
                "text": str(item["text"]),
                "label": "attack" if int(item["label"]) == 1 else "safe",
                "category": str(item["category"]),
                "attack_family": str(item["attack_family"]),
                "source_context": str(item["source_context"]),
                "pair_id": item["pair_id"],
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


def family_recall(rows: list[dict], predictions: list[bool]) -> None:
    totals = defaultdict(int)
    caught = defaultdict(int)

    for row, predicted_attack in zip(rows, predictions):
        if row["label"] != "attack":
            continue

        family = row["attack_family"]
        totals[family] += 1
        if predicted_attack:
            caught[family] += 1

    print("\nAttack-family recall")
    print("-" * 72)
    for family in sorted(totals):
        total = totals[family]
        hit = caught[family]
        print(f"{family:<34} {hit}/{total}  recall={hit / total:.3f}")


def print_errors(
    title: str,
    rows: list[dict],
    predictions: list[bool],
    semantic_scores: list[float],
) -> None:
    errors = []

    for row, predicted_attack, score in zip(
        rows, predictions, semantic_scores
    ):
        actual_attack = row["label"] == "attack"
        if actual_attack == predicted_attack:
            continue

        outcome = "FN" if actual_attack else "FP"
        errors.append((outcome, row, score))

    print(f"\n{title}: {len(errors)}")
    print("-" * 90)

    for outcome, row, score in errors:
        print(
            f"{outcome} | semantic={score:.3f} | "
            f"family={row['attack_family']} | "
            f"category={row['category']} | "
            f"{row['text']}"
        )


def benign_boundary_fpr(
    rows: list[dict],
    predictions: list[bool],
) -> tuple[int, int, float]:
    total = 0
    false_positives = 0

    for row, predicted_attack in zip(rows, predictions):
        if row["category"] != "benign_boundary":
            continue

        total += 1
        if predicted_attack:
            false_positives += 1

    rate = false_positives / total if total else 0.0
    return false_positives, total, rate


def main() -> None:
    print("Important: this script DOES NOT retrain or recalibrate the model.")
    print(
        "It evaluates the existing English-trained SemanticGuard "
        "with the fixed production threshold 0.40.\n"
    )

    dataset = load_dataset(DATASET_NAME)
    test_rows = to_rows(dataset["test"])

    safe_count = sum(row["label"] == "safe" for row in test_rows)
    attack_count = sum(row["label"] == "attack" for row in test_rows)

    print(f"Dataset: {DATASET_NAME}")
    print(
        f"Test: {len(test_rows)} | "
        f"safe={safe_count} | attack={attack_count}"
    )
    print(f"Semantic threshold: {SEMANTIC_THRESHOLD:.2f}\n")

    rule_guard = RuleGuard()
    policy = InputPolicy()
    semantic_guard = SemanticGuard()

    rule_predictions = []
    semantic_predictions = []
    semantic_scores = []

    for row in test_rows:
        rule_result = rule_guard.analyze(row["text"])
        rule_decision = policy.decide(rule_result.score)
        rule_attack = rule_decision.action == PolicyAction.BLOCK

        semantic_result = semantic_guard.analyze(row["text"])
        semantic_attack = semantic_result.score >= SEMANTIC_THRESHOLD

        rule_predictions.append(rule_attack)
        semantic_predictions.append(semantic_attack)
        semantic_scores.append(semantic_result.score)

    hybrid_predictions = [
        rule_attack or semantic_attack
        for rule_attack, semantic_attack in zip(
            rule_predictions,
            semantic_predictions,
        )
    ]

    rule_metrics = metrics_from_predictions(test_rows, rule_predictions)
    semantic_metrics = metrics_from_predictions(test_rows, semantic_predictions)
    hybrid_metrics = metrics_from_predictions(test_rows, hybrid_predictions)

    print("EXTERNAL TURKISH TEST RESULTS")
    print("=" * 90)
    print_metrics("RuleGuard", rule_metrics)
    print_metrics("SemanticGuard", semantic_metrics)
    print_metrics("Hybrid", hybrid_metrics)

    for name, predictions in (
        ("RuleGuard", rule_predictions),
        ("SemanticGuard", semantic_predictions),
        ("Hybrid", hybrid_predictions),
    ):
        fp, total, rate = benign_boundary_fpr(test_rows, predictions)
        print(
            f"{name:<14} benign_boundary FPR: "
            f"{fp}/{total} = {rate:.3f}"
        )

    family_recall(test_rows, hybrid_predictions)

    print_errors(
        "SemanticGuard errors",
        test_rows,
        semantic_predictions,
        semantic_scores,
    )

    print_errors(
        "Hybrid errors",
        test_rows,
        hybrid_predictions,
        semantic_scores,
    )

    print(
        "\nMethodology note: only the Turkish TEST split is used here. "
        "The existing SemanticGuard artifact is not retrained, and the "
        "0.40 threshold is not changed using this dataset. "
        "This is a cross-language external evaluation."
    )


if __name__ == "__main__":
    main()
