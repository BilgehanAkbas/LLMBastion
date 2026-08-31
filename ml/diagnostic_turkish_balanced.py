from __future__ import annotations

import sys
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
from ml.train_and_compare import metrics_from_predictions


EN_DATASET = "S-Labs/prompt-injection-dataset"
TR_TRAIN_DATASET = "3nesdeniz/turkish-conversation-prompt-injection"
DIAGNOSTIC_DATASET = "beratcmn/turkish-prompt-injections"

CURRENT_MODEL_PATH = Path("app/artifacts/semantic_guard.joblib")

CURRENT_THRESHOLD = 0.40
WORD_THRESHOLD = 0.35
CHAR_THRESHOLD = 0.30


def normalize(text: str) -> str:
    return " ".join(text.strip().lower().split())


def rows_from_binary_split(split) -> list[dict]:
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


def scores(model, rows: list[dict]) -> list[float]:
    return [
        float(value)
        for value in model.predict_proba(
            [row["text"] for row in rows]
        )[:, 1]
    ]


def predictions(values: list[float], threshold: float) -> list[bool]:
    return [value >= threshold for value in values]


def print_metrics(name: str, threshold: str, metrics) -> None:
    print(
        f"{name:<24} th={threshold:<4} | "
        f"P={metrics.precision:.3f} "
        f"R={metrics.recall:.3f} "
        f"F1={metrics.f1:.3f} "
        f"Acc={metrics.accuracy:.3f} "
        f"FPR={metrics.false_positive_rate:.3f} "
        f"FNR={metrics.false_negative_rate:.3f}"
    )
    print(
        f"{'':24} {'':8}  "
        f"TP={metrics.tp} FP={metrics.fp} "
        f"TN={metrics.tn} FN={metrics.fn}"
    )


def print_errors(
    name: str,
    rows: list[dict],
    preds: list[bool],
    model_scores: list[float] | None,
    limit: int = 10,
) -> None:
    errors = []

    for index, (row, predicted_attack) in enumerate(zip(rows, preds)):
        actual_attack = row["label"] == "attack"
        if actual_attack == predicted_attack:
            continue

        outcome = "FN" if actual_attack else "FP"
        score = None if model_scores is None else model_scores[index]
        errors.append((outcome, row, score))

    print(f"\n{name} ERRORS: {len(errors)}")
    print("=" * 90)

    for outcome, row, score in errors[:limit]:
        score_text = "" if score is None else f"score={score:.3f} | "
        print(
            f"{outcome} | {score_text}{row['text']}"
        )

    if len(errors) > limit:
        print(f"... {len(errors) - limit} more")


def compare_changes(
    rows: list[dict],
    baseline: list[bool],
    candidate: list[bool],
    candidate_name: str,
) -> None:
    rescued_attacks = 0
    lost_attacks = 0
    fixed_safe = 0
    broken_safe = 0

    for row, old, new in zip(rows, baseline, candidate):
        attack = row["label"] == "attack"

        if attack and not old and new:
            rescued_attacks += 1
        elif attack and old and not new:
            lost_attacks += 1
        elif not attack and old and not new:
            fixed_safe += 1
        elif not attack and not old and new:
            broken_safe += 1

    print(
        f"{candidate_name:<20} | "
        f"rescued attacks={rescued_attacks:>3} | "
        f"lost attacks={lost_attacks:>3} | "
        f"fixed safe FP={fixed_safe:>3} | "
        f"new safe FP={broken_safe:>3}"
    )


def main() -> None:
    print("BALANCED TURKISH DIAGNOSTIC BENCHMARK")
    print("This script does not overwrite semantic_guard.joblib.")
    print(
        "Important: this dataset is a Turkish translation of the Deepset "
        "prompt-injection dataset, so results are diagnostic, not a final "
        "independent benchmark.\n"
    )

    en = load_dataset(EN_DATASET)
    tr = load_dataset(TR_TRAIN_DATASET)
    diagnostic = load_dataset(DIAGNOSTIC_DATASET)

    en_train = rows_from_binary_split(en["train"])
    tr_train = rows_from_binary_split(tr["train"])
    tr_validation = rows_from_binary_split(tr["validation"])

    # Use the dataset's test split only. No threshold tuning here.
    test_rows = rows_from_binary_split(diagnostic["test"])

    blocked_texts = {
        normalize(row["text"])
        for row in tr_train + tr_validation
    }

    clean_rows = [
        row
        for row in test_rows
        if normalize(row["text"]) not in blocked_texts
    ]
    removed = len(test_rows) - len(clean_rows)

    safe_count = sum(row["label"] == "safe" for row in clean_rows)
    attack_count = sum(row["label"] == "attack" for row in clean_rows)

    print("DATA")
    print("=" * 90)
    print(f"English train:                 {len(en_train)}")
    print(f"Turkish train:                 {len(tr_train)}")
    print(f"Turkish validation:            {len(tr_validation)}")
    print(f"Diagnostic test original:      {len(test_rows)}")
    print(f"Removed TR train/val overlap:  {removed}")
    print(f"Diagnostic clean test:         {len(clean_rows)}")
    print(f"Safe / Attack:                 {safe_count} / {attack_count}")
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

    current_scores = scores(current, clean_rows)
    word_scores = scores(word, clean_rows)
    char_scores = scores(char, clean_rows)

    current_preds = predictions(current_scores, CURRENT_THRESHOLD)
    word_preds = predictions(word_scores, WORD_THRESHOLD)
    char_preds = predictions(char_scores, CHAR_THRESHOLD)

    rule_guard = RuleGuard()
    policy = InputPolicy()
    rule_preds = []

    for row in clean_rows:
        result = rule_guard.analyze(row["text"])
        decision = policy.decide(result.score)
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

    results = (
        ("RuleGuard", "-", rule_preds, None),
        ("Current Semantic", f"{CURRENT_THRESHOLD:.2f}", current_preds, current_scores),
        ("Current Hybrid", f"{CURRENT_THRESHOLD:.2f}", current_hybrid, current_scores),
        ("Multilingual WORD", f"{WORD_THRESHOLD:.2f}", word_preds, word_scores),
        ("WORD + RuleGuard", f"{WORD_THRESHOLD:.2f}", word_hybrid, word_scores),
        ("Multilingual CHAR", f"{CHAR_THRESHOLD:.2f}", char_preds, char_scores),
        ("CHAR + RuleGuard", f"{CHAR_THRESHOLD:.2f}", char_hybrid, char_scores),
    )

    print("RESULTS")
    print("=" * 90)
    for name, threshold, preds, _ in results:
        metrics = metrics_from_predictions(clean_rows, preds)
        print_metrics(name, threshold, metrics)

    print("\nCHANGES VS CURRENT SEMANTIC")
    print("=" * 90)
    compare_changes(clean_rows, current_preds, word_preds, "Multilingual WORD")
    compare_changes(clean_rows, current_preds, char_preds, "Multilingual CHAR")

    print_errors(
        "CURRENT SEMANTIC",
        clean_rows,
        current_preds,
        current_scores,
    )
    print_errors(
        "MULTILINGUAL WORD",
        clean_rows,
        word_preds,
        word_scores,
    )
    print_errors(
        "MULTILINGUAL CHAR",
        clean_rows,
        char_preds,
        char_scores,
    )

    print(
        "\nMethodology note: WORD/CHAR are trained only on S-Labs train + "
        "3nesdeniz Turkish train. Thresholds remain fixed at values chosen "
        "in the previous 3nesdeniz validation experiment. The BeratCMN test "
        "split is used only for this diagnostic evaluation and is not used "
        "for fitting or threshold selection."
    )


if __name__ == "__main__":
    main()
