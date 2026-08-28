from __future__ import annotations

import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.linear_model import LogisticRegression
from sklearn.pipeline import Pipeline

from app.guards.input.rule_guard import RuleGuard
from app.policies.input_policy import InputPolicy, PolicyAction
from evaluation.evaluate_rule_guard import calculate_metrics


TRAIN_PATH = Path(__file__).with_name("training_v1.jsonl")
TEST_PATH = PROJECT_ROOT / "evaluation" / "prompt_injection_v1.jsonl"
ML_THRESHOLD = 0.50


def load_jsonl(path: Path) -> list[dict]:
    rows = []
    with path.open(encoding="utf-8") as f:
        for line in f:
            if line.strip():
                rows.append(json.loads(line))
    return rows


def build_model() -> Pipeline:
    return Pipeline([
        ("tfidf", TfidfVectorizer(
            lowercase=True,
            ngram_range=(1, 2),
            sublinear_tf=True,
        )),
        ("classifier", LogisticRegression(
            max_iter=1000,
            random_state=42,
        )),
    ])


def metrics_from_predictions(rows: list[dict], predictions: list[bool]):
    tp = fp = tn = fn = 0
    for row, predicted_attack in zip(rows, predictions):
        actual_attack = row["label"] == "attack"
        if actual_attack and predicted_attack:
            tp += 1
        elif not actual_attack and predicted_attack:
            fp += 1
        elif not actual_attack and not predicted_attack:
            tn += 1
        else:
            fn += 1
    return calculate_metrics(tp, fp, tn, fn)


def print_metrics(name: str, metrics) -> None:
    print(
        f"{name:<14} "
        f"P={metrics.precision:.3f}  "
        f"R={metrics.recall:.3f}  "
        f"F1={metrics.f1:.3f}  "
        f"FPR={metrics.false_positive_rate:.3f}  "
        f"FNR={metrics.false_negative_rate:.3f}"
    )


def main() -> None:
    train_rows = load_jsonl(TRAIN_PATH)
    test_rows = load_jsonl(TEST_PATH)

    train_texts = {r["text"].strip().lower() for r in train_rows}
    test_texts = {r["text"].strip().lower() for r in test_rows}
    overlap = train_texts & test_texts

    if overlap:
        raise RuntimeError(
            f"Train/test leakage detected: {len(overlap)} exact duplicate prompts"
        )

    print(
        f"Training set: {len(train_rows)} "
        f"({sum(r['label'] == 'safe' for r in train_rows)} safe / "
        f"{sum(r['label'] == 'attack' for r in train_rows)} attack)"
    )
    print(
        f"Test set:     {len(test_rows)} "
        f"({sum(r['label'] == 'safe' for r in test_rows)} safe / "
        f"{sum(r['label'] == 'attack' for r in test_rows)} attack)"
    )
    print("Exact train/test overlap: 0")
    print()

    model = build_model()
    model.fit(
        [r["text"] for r in train_rows],
        [1 if r["label"] == "attack" else 0 for r in train_rows],
    )

    ml_probs = model.predict_proba([r["text"] for r in test_rows])[:, 1]
    ml_predictions = [p >= ML_THRESHOLD for p in ml_probs]

    guard = RuleGuard()
    policy = InputPolicy()
    regex_predictions = []

    for row in test_rows:
        result = guard.analyze(row["text"])
        decision = policy.decide(result.score)
        regex_predictions.append(decision.action == PolicyAction.BLOCK)

    hybrid_predictions = [
        regex_attack or ml_attack
        for regex_attack, ml_attack in zip(regex_predictions, ml_predictions)
    ]

    regex_metrics = metrics_from_predictions(test_rows, regex_predictions)
    ml_metrics = metrics_from_predictions(test_rows, ml_predictions)
    hybrid_metrics = metrics_from_predictions(test_rows, hybrid_predictions)

    print("Comparison on unseen evaluation set")
    print("-" * 76)
    print_metrics("Regex only", regex_metrics)
    print_metrics("ML only", ml_metrics)
    print_metrics("Hybrid OR", hybrid_metrics)
    print()

    rescued = []
    for row, regex_attack, ml_attack, prob in zip(
        test_rows, regex_predictions, ml_predictions, ml_probs
    ):
        if row["label"] == "attack" and not regex_attack and ml_attack:
            rescued.append((row, prob))

    print(f"Attacks missed by Regex but caught by ML: {len(rescued)}")
    print("-" * 76)
    for row, prob in rescued[:12]:
        print(f'{row["id"]} | ml={prob:.3f} | {row["text"]}')
    if len(rescued) > 12:
        print(f"... {len(rescued) - 12} more")

    print()
    print(
        "Important: this is still a synthetic experiment. "
        "Do not treat the best score as production performance."
    )


if __name__ == "__main__":
    main()
