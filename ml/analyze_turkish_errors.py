from __future__ import annotations

from collections import defaultdict
from pathlib import Path

import joblib
from datasets import load_dataset

DATASET_NAME = "3nesdeniz/turkish-conversation-prompt-injection"
MODEL_PATH = Path("app/artifacts/semantic_guard.joblib")
THRESHOLD = 0.40


def load_rows():
    ds = load_dataset(DATASET_NAME)["test"]
    rows = []
    for item in ds:
        rows.append(
            {
                "id": str(item["id"]),
                "text": str(item["text"]),
                "label": "attack" if int(item["label"]) == 1 else "safe",
                "category": str(item["category"]),
                "attack_family": str(item["attack_family"]),
            }
        )
    return rows


def sigmoid_score(model, text: str) -> float:
    return float(model.predict_proba([text])[0][1])


def vocabulary_coverage(vectorizer, text: str) -> tuple[int, int, float]:
    analyzer = vectorizer.build_analyzer()
    produced = set(analyzer(text))
    if not produced:
        return 0, 0, 0.0

    vocabulary = vectorizer.vocabulary_
    known = sum(token in vocabulary for token in produced)
    total = len(produced)
    return known, total, known / total


def top_contributions(model, text: str, limit: int = 5):
    vectorizer = model.named_steps["tfidf"]
    classifier = model.named_steps["classifier"]

    x = vectorizer.transform([text]).tocsr()
    feature_names = vectorizer.get_feature_names_out()
    coefs = classifier.coef_[0]

    contributions = []
    for idx, value in zip(x.indices, x.data):
        contribution = float(value * coefs[idx])
        contributions.append(
            (feature_names[idx], contribution)
        )

    positive = sorted(
        [x for x in contributions if x[1] > 0],
        key=lambda x: x[1],
        reverse=True,
    )[:limit]

    negative = sorted(
        [x for x in contributions if x[1] < 0],
        key=lambda x: x[1],
    )[:limit]

    return positive, negative


def avg(values):
    return sum(values) / len(values) if values else 0.0


def main():
    if not MODEL_PATH.exists():
        raise RuntimeError(
            "Model artifact not found. Run: python ml/train_semantic_guard.py"
        )

    model = joblib.load(MODEL_PATH)
    vectorizer = model.named_steps["tfidf"]
    classifier = model.named_steps["classifier"]

    rows = load_rows()

    print("MODEL / VOCABULARY")
    print("=" * 90)
    print(f"Vocabulary size: {len(vectorizer.vocabulary_)}")
    print(f"Classifier intercept: {float(classifier.intercept_[0]):.6f}")
    print(f"Threshold: {THRESHOLD:.2f}")
    print()

    feature_names = vectorizer.get_feature_names_out()
    coefs = classifier.coef_[0]

    ranked = sorted(
        zip(feature_names, coefs),
        key=lambda x: x[1],
        reverse=True,
    )

    print("Top global ATTACK features")
    print("-" * 90)
    for feature, coef in ranked[:15]:
        print(f"{feature:<36} coef={coef:+.4f}")

    print("\nTop global SAFE features")
    print("-" * 90)
    for feature, coef in ranked[-15:]:
        print(f"{feature:<36} coef={coef:+.4f}")

    buckets = defaultdict(list)
    category_stats = defaultdict(lambda: {"total": 0, "errors": 0})
    family_stats = defaultdict(lambda: {"total": 0, "caught": 0})
    error_rows = []

    for row in rows:
        score = sigmoid_score(model, row["text"])
        predicted_attack = score >= THRESHOLD
        actual_attack = row["label"] == "attack"

        known, total, coverage = vocabulary_coverage(
            vectorizer, row["text"]
        )

        outcome = (
            "TP" if actual_attack and predicted_attack
            else "FN" if actual_attack
            else "FP" if predicted_attack
            else "TN"
        )

        buckets[outcome].append(coverage)

        category_stats[row["category"]]["total"] += 1
        if outcome in ("FP", "FN"):
            category_stats[row["category"]]["errors"] += 1

        if actual_attack:
            family = row["attack_family"]
            family_stats[family]["total"] += 1
            if predicted_attack:
                family_stats[family]["caught"] += 1

        if outcome in ("FP", "FN"):
            positive, negative = top_contributions(
                model, row["text"], limit=5
            )
            error_rows.append(
                {
                    **row,
                    "outcome": outcome,
                    "score": score,
                    "known": known,
                    "total": total,
                    "coverage": coverage,
                    "positive": positive,
                    "negative": negative,
                }
            )

    print("\nVOCABULARY COVERAGE")
    print("=" * 90)
    for outcome in ("TP", "TN", "FP", "FN"):
        values = buckets[outcome]
        print(
            f"{outcome}: n={len(values):>3} | "
            f"avg coverage={avg(values):.3f}"
        )

    all_coverages = (
        buckets["TP"] + buckets["TN"] +
        buckets["FP"] + buckets["FN"]
    )
    print(
        f"ALL: n={len(all_coverages):>3} | "
        f"avg coverage={avg(all_coverages):.3f}"
    )

    print("\nSAFE CATEGORY ERROR RATES")
    print("=" * 90)
    for category in sorted(category_stats):
        stat = category_stats[category]
        print(
            f"{category:<28} "
            f"errors={stat['errors']:>2}/{stat['total']:<2} "
            f"rate={stat['errors']/stat['total']:.3f}"
        )

    print("\nATTACK-FAMILY RECALL")
    print("=" * 90)
    for family in sorted(family_stats):
        stat = family_stats[family]
        print(
            f"{family:<34} "
            f"{stat['caught']}/{stat['total']} "
            f"recall={stat['caught']/stat['total']:.3f}"
        )

    print("\nERROR DETAILS")
    print("=" * 90)
    for row in error_rows:
        print(
            f"{row['outcome']} | score={row['score']:.3f} | "
            f"coverage={row['known']}/{row['total']} "
            f"({row['coverage']:.3f}) | "
            f"category={row['category']} | "
            f"family={row['attack_family']}"
        )
        print(row["text"])

        if row["positive"]:
            print(
                "  attack pushes: "
                + ", ".join(
                    f"{feature}({value:+.3f})"
                    for feature, value in row["positive"]
                )
            )
        else:
            print("  attack pushes: none")

        if row["negative"]:
            print(
                "  safe pushes:   "
                + ", ".join(
                    f"{feature}({value:+.3f})"
                    for feature, value in row["negative"]
                )
            )
        else:
            print("  safe pushes:   none")

        print("-" * 90)


if __name__ == "__main__":
    main()
