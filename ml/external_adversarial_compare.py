from __future__ import annotations

import sys
from collections import defaultdict
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import joblib
from datasets import load_dataset
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.linear_model import LogisticRegression
from sklearn.pipeline import Pipeline

from app.guards.input.rule_guard import RuleGuard
from app.policies.input_policy import InputPolicy, PolicyAction


EN_DATASET = "S-Labs/prompt-injection-dataset"
TR_TRAIN_DATASET = "3nesdeniz/turkish-conversation-prompt-injection"
ADVERSARIAL_DATASET = "AltaySec/turkish-llm-injection"

CURRENT_MODEL_PATH = Path("app/artifacts/semantic_guard.joblib")

CURRENT_THRESHOLD = 0.40
WORD_THRESHOLD = 0.35
CHAR_THRESHOLD = 0.30


def normalize(text: str) -> str:
    return " ".join(text.strip().lower().split())


def binary_rows(split) -> list[dict]:
    rows = []
    for item in split:
        rows.append({
            "text": str(item["text"]),
            "label": "attack" if int(item["label"]) == 1 else "safe",
        })
    return rows


def attack_rows(split) -> list[dict]:
    rows = []
    for item in split:
        rows.append({
            "id": str(item["id"]),
            "text": str(item["prompt"]),
            "category": str(item["category"]),
            "subcategory": str(item["subcategory"]),
            "severity": str(item["severity"]),
            "language": str(item["language"]),
            "expected_failure_mode": str(item["expected_failure_mode"]),
        })
    return rows


def build_word_model() -> Pipeline:
    return Pipeline([
        (
            "tfidf",
            TfidfVectorizer(
                lowercase=True,
                ngram_range=(1, 2),
                sublinear_tf=True,
            ),
        ),
        (
            "classifier",
            LogisticRegression(
                max_iter=1000,
                random_state=42,
            ),
        ),
    ])


def build_char_model() -> Pipeline:
    return Pipeline([
        (
            "tfidf",
            TfidfVectorizer(
                analyzer="char_wb",
                ngram_range=(3, 5),
                sublinear_tf=True,
                min_df=2,
                max_features=100_000,
            ),
        ),
        (
            "classifier",
            LogisticRegression(
                max_iter=1000,
                random_state=42,
            ),
        ),
    ])


def fit(model: Pipeline, rows: list[dict]) -> Pipeline:
    model.fit(
        [row["text"] for row in rows],
        [1 if row["label"] == "attack" else 0 for row in rows],
    )
    return model


def predict_scores(model, rows: list[dict]) -> list[float]:
    return [
        float(x)
        for x in model.predict_proba(
            [row["text"] for row in rows]
        )[:, 1]
    ]


def predict(scores: list[float], threshold: float) -> list[bool]:
    return [score >= threshold for score in scores]


def recall(predictions: list[bool]) -> tuple[int, int, float]:
    caught = sum(predictions)
    total = len(predictions)
    return caught, total, caught / total if total else 0.0


def print_recall(name: str, predictions: list[bool]) -> None:
    caught, total, value = recall(predictions)
    print(
        f"{name:<24} {caught:>3}/{total:<3} "
        f"recall={value:.3f}"
    )


def grouped_recall(
    rows: list[dict],
    predictions: list[bool],
    field: str,
    title: str,
) -> None:
    stats = defaultdict(lambda: [0, 0])

    for row, detected in zip(rows, predictions):
        key = row[field]
        stats[key][1] += 1
        if detected:
            stats[key][0] += 1

    print(f"\n{title}")
    print("=" * 90)

    for key in sorted(stats):
        caught, total = stats[key]
        print(
            f"{key:<34} "
            f"{caught:>3}/{total:<3} "
            f"recall={caught / total:.3f}"
        )


def print_misses(
    rows: list[dict],
    predictions: list[bool],
    scores: list[float] | None,
    title: str,
    limit: int = 20,
) -> None:
    misses = []

    for index, (row, detected) in enumerate(zip(rows, predictions)):
        if detected:
            continue

        score = None if scores is None else scores[index]
        misses.append((row, score))

    print(f"\n{title}: {len(misses)}")
    print("=" * 90)

    for row, score in misses[:limit]:
        score_text = "" if score is None else f"score={score:.3f} | "
        print(
            f"{score_text}"
            f"category={row['category']} | "
            f"severity={row['severity']} | "
            f"lang={row['language']} | "
            f"{row['text']}"
        )

    if len(misses) > limit:
        print(f"... {len(misses) - limit} more")


def main() -> None:
    print("INDEPENDENT ADVERSARIAL RECALL BENCHMARK")
    print("This script does not overwrite semantic_guard.joblib.")
    print(
        "AltaySec contains attack payloads only, so this benchmark "
        "measures attack recall, not precision/FPR.\n"
    )

    en = load_dataset(EN_DATASET)
    tr = load_dataset(TR_TRAIN_DATASET)
    altay = load_dataset(ADVERSARIAL_DATASET)

    en_train = binary_rows(en["train"])
    tr_train = binary_rows(tr["train"])
    tr_validation = binary_rows(tr["validation"])

    all_altay_rows = attack_rows(altay["train"])

    blocked_texts = {
        normalize(row["text"])
        for row in tr_train + tr_validation
    }

    clean_rows = [
        row
        for row in all_altay_rows
        if normalize(row["text"]) not in blocked_texts
    ]
    removed = len(all_altay_rows) - len(clean_rows)

    print("DATA")
    print("=" * 90)
    print(f"English train:               {len(en_train)}")
    print(f"Turkish train:               {len(tr_train)}")
    print(f"Turkish validation:          {len(tr_validation)}")
    print(f"AltaySec original:           {len(all_altay_rows)}")
    print(f"Removed TR train/val overlap:{removed}")
    print(f"AltaySec clean benchmark:    {len(clean_rows)}")
    print()

    if not CURRENT_MODEL_PATH.exists():
        raise RuntimeError(
            "Current SemanticGuard model artifact not found. "
            "Run: python ml/train_semantic_guard.py"
        )

    current = joblib.load(CURRENT_MODEL_PATH)

    combined_train = en_train + tr_train
    word = fit(build_word_model(), combined_train)
    char = fit(build_char_model(), combined_train)

    current_scores = predict_scores(current, clean_rows)
    word_scores = predict_scores(word, clean_rows)
    char_scores = predict_scores(char, clean_rows)

    current_preds = predict(current_scores, CURRENT_THRESHOLD)
    word_preds = predict(word_scores, WORD_THRESHOLD)
    char_preds = predict(char_scores, CHAR_THRESHOLD)

    rule_guard = RuleGuard()
    input_policy = InputPolicy()

    rule_preds = []
    for row in clean_rows:
        result = rule_guard.analyze(row["text"])
        decision = input_policy.decide(result.score)
        rule_preds.append(
            decision.action == PolicyAction.BLOCK
        )

    current_hybrid = [
        rule or ml
        for rule, ml in zip(rule_preds, current_preds)
    ]
    word_hybrid = [
        rule or ml
        for rule, ml in zip(rule_preds, word_preds)
    ]
    char_hybrid = [
        rule or ml
        for rule, ml in zip(rule_preds, char_preds)
    ]

    print("OVERALL ATTACK RECALL")
    print("=" * 90)
    print_recall("RuleGuard", rule_preds)
    print_recall("Current Semantic", current_preds)
    print_recall("Current Hybrid", current_hybrid)
    print_recall("Multilingual WORD", word_preds)
    print_recall("WORD + RuleGuard", word_hybrid)
    print_recall("Multilingual CHAR", char_preds)
    print_recall("CHAR + RuleGuard", char_hybrid)

    grouped_recall(
        clean_rows,
        word_preds,
        "category",
        "MULTILINGUAL WORD — CATEGORY RECALL",
    )
    grouped_recall(
        clean_rows,
        char_preds,
        "category",
        "MULTILINGUAL CHAR — CATEGORY RECALL",
    )
    grouped_recall(
        clean_rows,
        word_preds,
        "severity",
        "MULTILINGUAL WORD — SEVERITY RECALL",
    )
    grouped_recall(
        clean_rows,
        char_preds,
        "severity",
        "MULTILINGUAL CHAR — SEVERITY RECALL",
    )
    grouped_recall(
        clean_rows,
        word_preds,
        "language",
        "MULTILINGUAL WORD — LANGUAGE RECALL",
    )
    grouped_recall(
        clean_rows,
        char_preds,
        "language",
        "MULTILINGUAL CHAR — LANGUAGE RECALL",
    )

    print_misses(
        clean_rows,
        word_preds,
        word_scores,
        "MULTILINGUAL WORD MISSES",
    )
    print_misses(
        clean_rows,
        char_preds,
        char_scores,
        "MULTILINGUAL CHAR MISSES",
    )

    print(
        "\nMethodology note: Multilingual WORD/CHAR are trained only on "
        "S-Labs train + 3nesdeniz Turkish train. Their thresholds come "
        "from the previous Turkish validation experiment. Exact overlaps "
        "with 3nesdeniz train/validation are removed from AltaySec before "
        "evaluation. No AltaySec example is used for training or threshold selection."
    )


if __name__ == "__main__":
    main()
