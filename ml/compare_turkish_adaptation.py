from __future__ import annotations

from dataclasses import dataclass

import joblib
from datasets import load_dataset
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.linear_model import LogisticRegression
from sklearn.pipeline import Pipeline

from ml.train_and_compare import metrics_from_predictions


EN_DATASET = "S-Labs/prompt-injection-dataset"
TR_DATASET = "3nesdeniz/turkish-conversation-prompt-injection"
CURRENT_MODEL_PATH = "app/artifacts/semantic_guard.joblib"

THRESHOLDS = (
    0.30, 0.35, 0.40, 0.45, 0.50,
    0.55, 0.60, 0.65, 0.70, 0.75, 0.80,
)


def rows_from_split(split) -> list[dict]:
    rows = []
    for item in split:
        rows.append({
            "text": str(item["text"]),
            "label": "attack" if int(item["label"]) == 1 else "safe",
        })
    return rows


def normalized_texts(rows: list[dict]) -> set[str]:
    return {
        " ".join(row["text"].strip().lower().split())
        for row in rows
    }


def probabilities(model, rows: list[dict]):
    return model.predict_proba(
        [row["text"] for row in rows]
    )[:, 1]


def predictions(probs, threshold: float) -> list[bool]:
    return [float(p) >= threshold for p in probs]


def choose_threshold(rows: list[dict], probs) -> tuple[float, object]:
    candidates = []

    for threshold in THRESHOLDS:
        preds = predictions(probs, threshold)
        metrics = metrics_from_predictions(rows, preds)
        candidates.append((threshold, metrics))

    return max(
        candidates,
        key=lambda item: (
            item[1].f1,
            -item[1].false_positive_rate,
            item[1].recall,
        ),
    )


def print_metrics(name: str, threshold: float, metrics) -> None:
    print(
        f"{name:<26} th={threshold:.2f} | "
        f"P={metrics.precision:.3f} "
        f"R={metrics.recall:.3f} "
        f"F1={metrics.f1:.3f} "
        f"FPR={metrics.false_positive_rate:.3f} "
        f"FNR={metrics.false_negative_rate:.3f}"
    )


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


def fit(model, rows: list[dict]):
    model.fit(
        [row["text"] for row in rows],
        [1 if row["label"] == "attack" else 0 for row in rows],
    )
    return model


def main() -> None:
    print("This is an EXPERIMENT only.")
    print("It does not overwrite semantic_guard.joblib.")
    print("The Turkish TEST split is intentionally NOT used.\n")

    en = load_dataset(EN_DATASET)
    tr = load_dataset(TR_DATASET)

    en_train = rows_from_split(en["train"])
    en_validation = rows_from_split(en["validation"])

    tr_train = rows_from_split(tr["train"])
    tr_validation = rows_from_split(tr["validation"])

    overlap = normalized_texts(tr_train) & normalized_texts(tr_validation)

    print("DATA")
    print("=" * 90)
    print(f"English train:       {len(en_train)}")
    print(f"English validation:  {len(en_validation)}")
    print(f"Turkish train:       {len(tr_train)}")
    print(f"Turkish validation:  {len(tr_validation)}")
    print(f"TR train/val overlap:{len(overlap)}")
    print()

    current = joblib.load(CURRENT_MODEL_PATH)
    current_tr_probs = probabilities(current, tr_validation)
    current_en_probs = probabilities(current, en_validation)

    current_fixed_tr = metrics_from_predictions(
        tr_validation,
        predictions(current_tr_probs, 0.40),
    )
    current_fixed_en = metrics_from_predictions(
        en_validation,
        predictions(current_en_probs, 0.40),
    )

    current_best_threshold, current_best_tr = choose_threshold(
        tr_validation,
        current_tr_probs,
    )
    current_best_en = metrics_from_predictions(
        en_validation,
        predictions(current_en_probs, current_best_threshold),
    )

    combined_train = en_train + tr_train
    word = fit(build_word_model(), combined_train)

    word_tr_probs = probabilities(word, tr_validation)
    word_en_probs = probabilities(word, en_validation)

    word_threshold, word_tr = choose_threshold(
        tr_validation,
        word_tr_probs,
    )
    word_en = metrics_from_predictions(
        en_validation,
        predictions(word_en_probs, word_threshold),
    )

    char = fit(build_char_model(), combined_train)

    char_tr_probs = probabilities(char, tr_validation)
    char_en_probs = probabilities(char, en_validation)

    char_threshold, char_tr = choose_threshold(
        tr_validation,
        char_tr_probs,
    )
    char_en = metrics_from_predictions(
        en_validation,
        predictions(char_en_probs, char_threshold),
    )

    print("TURKISH VALIDATION")
    print("=" * 90)
    print_metrics(
        "Current model / fixed",
        0.40,
        current_fixed_tr,
    )
    print_metrics(
        "Current / tuned threshold",
        current_best_threshold,
        current_best_tr,
    )
    print_metrics(
        "Multilingual WORD",
        word_threshold,
        word_tr,
    )
    print_metrics(
        "Multilingual CHAR",
        char_threshold,
        char_tr,
    )

    print("\nENGLISH VALIDATION — same selected thresholds")
    print("=" * 90)
    print_metrics(
        "Current model / fixed",
        0.40,
        current_fixed_en,
    )
    print_metrics(
        "Current / TR-tuned th.",
        current_best_threshold,
        current_best_en,
    )
    print_metrics(
        "Multilingual WORD",
        word_threshold,
        word_en,
    )
    print_metrics(
        "Multilingual CHAR",
        char_threshold,
        char_en,
    )

    print(
        "\nInterpretation rules:\n"
        "- If threshold tuning barely helps, the problem is not just threshold calibration.\n"
        "- If multilingual WORD improves strongly, Turkish training data fixes vocabulary blindness.\n"
        "- If CHAR beats WORD, character n-grams may help multilingual/obfuscated inputs.\n"
        "- English validation is printed to catch regressions after Turkish adaptation.\n"
        "- These are development-validation results, NOT final test claims."
    )


if __name__ == "__main__":
    main()
