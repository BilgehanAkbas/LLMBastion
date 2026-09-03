from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import (
    accuracy_score,
    confusion_matrix,
    f1_score,
    precision_score,
    recall_score,
)
from sklearn.pipeline import FeatureUnion, Pipeline


def load_jsonl(path: Path):
    rows = [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    texts = [row["text"] for row in rows]
    labels = np.asarray(
        [1 if row["label"] == "attack" else 0 for row in rows],
        dtype=int,
    )
    return rows, texts, labels


def build_models():
    classifier = lambda: LogisticRegression(
        max_iter=1500,
        random_state=42,
    )

    word = Pipeline([
        (
            "tfidf",
            TfidfVectorizer(
                lowercase=True,
                ngram_range=(1, 2),
                sublinear_tf=True,
            ),
        ),
        ("classifier", classifier()),
    ])

    char = Pipeline([
        (
            "tfidf",
            TfidfVectorizer(
                analyzer="char_wb",
                lowercase=True,
                ngram_range=(3, 5),
                sublinear_tf=True,
            ),
        ),
        ("classifier", classifier()),
    ])

    hybrid = Pipeline([
        (
            "features",
            FeatureUnion([
                (
                    "word",
                    TfidfVectorizer(
                        lowercase=True,
                        ngram_range=(1, 2),
                        sublinear_tf=True,
                    ),
                ),
                (
                    "char",
                    TfidfVectorizer(
                        analyzer="char_wb",
                        lowercase=True,
                        ngram_range=(3, 5),
                        sublinear_tf=True,
                    ),
                ),
            ]),
        ),
        ("classifier", classifier()),
    ])

    return {
        "word_v2_baseline": word,
        "char_wb": char,
        "hybrid_word_char": hybrid,
    }


def metrics(y_true, probabilities, threshold):
    y_pred = (probabilities >= threshold).astype(int)
    tn, fp, fn, tp = confusion_matrix(
        y_true,
        y_pred,
        labels=[0, 1],
    ).ravel()

    return {
        "threshold": round(float(threshold), 4),
        "precision": round(float(precision_score(
            y_true, y_pred, zero_division=0
        )), 4),
        "recall": round(float(recall_score(
            y_true, y_pred, zero_division=0
        )), 4),
        "f1": round(float(f1_score(
            y_true, y_pred, zero_division=0
        )), 4),
        "accuracy": round(float(accuracy_score(
            y_true, y_pred
        )), 4),
        "fpr": round(float(fp / (fp + tn)) if fp + tn else 0.0, 4),
        "fnr": round(float(fn / (fn + tp)) if fn + tp else 0.0, 4),
        "tp": int(tp),
        "fp": int(fp),
        "tn": int(tn),
        "fn": int(fn),
    }


def regression_metrics(
    benign_probabilities,
    attack_probabilities,
    threshold,
):
    benign_fp = int((benign_probabilities >= threshold).sum())
    attack_tp = int((attack_probabilities >= threshold).sum())

    return {
        "benign_count": int(len(benign_probabilities)),
        "benign_false_positives": benign_fp,
        "benign_fpr": round(
            benign_fp / len(benign_probabilities),
            4,
        ),
        "attack_count": int(len(attack_probabilities)),
        "attack_blocked": attack_tp,
        "attack_recall": round(
            attack_tp / len(attack_probabilities),
            4,
        ),
    }


def rank_candidate(validation, regression):
    # Prefer candidates that keep attack recall high while materially reducing
    # benign false positives. This score is only a report aid; it does not
    # modify runtime configuration.
    penalty = (
        regression["benign_fpr"] * 0.40
        + validation["fpr"] * 0.20
    )
    return round(
        validation["f1"]
        + regression["attack_recall"] * 0.25
        - penalty,
        6,
    )


def main():
    parser = argparse.ArgumentParser(
        description=(
            "Compare SemanticGuard candidates using train + validation "
            "+ an explicit regression set. The locked test is never read."
        )
    )
    parser.add_argument(
        "--train",
        default="data/llmbastion_dataset/data/train.jsonl",
    )
    parser.add_argument(
        "--validation",
        default="data/llmbastion_dataset/data/validation.jsonl",
    )
    parser.add_argument(
        "--benign-regression",
        default="data/semantic_guard_regression/benign.jsonl",
    )
    parser.add_argument(
        "--attack-regression",
        default="data/semantic_guard_regression/attacks.jsonl",
    )
    parser.add_argument(
        "--report",
        default="ml/semantic_guard_v3_experiment_report.json",
    )
    args = parser.parse_args()

    train_path = Path(args.train)
    validation_path = Path(args.validation)
    benign_path = Path(args.benign_regression)
    attack_path = Path(args.attack_regression)

    forbidden = "locked_test"
    for path in (
        train_path,
        validation_path,
        benign_path,
        attack_path,
    ):
        if forbidden in str(path).lower():
            raise ValueError(
                "This experiment must not read locked_test data."
            )

    _, train_texts, train_y = load_jsonl(train_path)
    _, validation_texts, validation_y = load_jsonl(validation_path)
    benign_rows, benign_texts, _ = load_jsonl(benign_path)
    attack_rows, attack_texts, _ = load_jsonl(attack_path)

    thresholds = np.arange(0.45, 0.701, 0.01)
    report = {
        "policy": {
            "training_source": str(train_path),
            "selection_source": str(validation_path),
            "locked_test_used": False,
            "threshold_grid": [
                round(float(x), 2) for x in thresholds
            ],
        },
        "models": {},
        "ranked_candidates": [],
    }

    ranking = []

    for model_name, model in build_models().items():
        print(f"Training {model_name}...")
        model.fit(train_texts, train_y)

        validation_p = model.predict_proba(validation_texts)[:, 1]
        benign_p = model.predict_proba(benign_texts)[:, 1]
        attack_p = model.predict_proba(attack_texts)[:, 1]

        fixed_051 = {
            "validation": metrics(
                validation_y,
                validation_p,
                0.51,
            ),
            "regression": regression_metrics(
                benign_p,
                attack_p,
                0.51,
            ),
        }

        threshold_rows = []
        for threshold in thresholds:
            val = metrics(
                validation_y,
                validation_p,
                threshold,
            )
            reg = regression_metrics(
                benign_p,
                attack_p,
                threshold,
            )
            row = {
                "threshold": round(float(threshold), 2),
                "validation": val,
                "regression": reg,
                "rank_score": rank_candidate(val, reg),
                "meets_guardrails": bool(
                    val["recall"] >= 0.93
                    and reg["attack_recall"] >= 0.90
                    and reg["benign_fpr"] <= 0.10
                ),
            }
            threshold_rows.append(row)
            if row["meets_guardrails"]:
                ranking.append({
                    "model": model_name,
                    **row,
                })

        prompt_scores = []
        for row, probability in zip(benign_rows, benign_p):
            prompt_scores.append({
                "label": "safe",
                "source": row.get("source"),
                "text": row["text"],
                "score": round(float(probability), 4),
            })
        for row, probability in zip(attack_rows, attack_p):
            prompt_scores.append({
                "label": "attack",
                "source": row.get("source"),
                "text": row["text"],
                "score": round(float(probability), 4),
            })

        report["models"][model_name] = {
            "fixed_threshold_0_51": fixed_051,
            "threshold_sweep": threshold_rows,
            "regression_prompt_scores": prompt_scores,
        }

    ranking.sort(
        key=lambda row: (
            row["rank_score"],
            row["validation"]["f1"],
            -row["validation"]["fpr"],
        ),
        reverse=True,
    )
    report["ranked_candidates"] = ranking[:15]

    output_path = Path(args.report)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )

    print()
    print("Locked test used: NO")
    print(f"Report: {output_path}")
    print()
    print("Top candidates:")
    if not ranking:
        print("No candidate met all guardrails.")
    else:
        for row in ranking[:10]:
            val = row["validation"]
            reg = row["regression"]
            print(
                f"{row['model']:18} t={row['threshold']:.2f} "
                f"val_f1={val['f1']:.3f} "
                f"val_recall={val['recall']:.3f} "
                f"val_fpr={val['fpr']:.3f} "
                f"reg_benign_fpr={reg['benign_fpr']:.3f} "
                f"reg_attack_recall={reg['attack_recall']:.3f}"
            )


if __name__ == "__main__":
    main()
