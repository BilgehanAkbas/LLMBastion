
from __future__ import annotations

import argparse
import json
from pathlib import Path

import joblib
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
from sklearn.pipeline import Pipeline


def load_jsonl(path: Path):
    rows = [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    texts = [r["text"] for r in rows]
    y = np.array([1 if r["label"] == "attack" else 0 for r in rows], dtype=int)
    return rows, texts, y


def metrics(y_true, probs, threshold):
    pred = (probs >= threshold).astype(int)
    tn, fp, fn, tp = confusion_matrix(y_true, pred, labels=[0, 1]).ravel()
    return {
        "threshold": round(float(threshold), 4),
        "precision": round(float(precision_score(y_true, pred, zero_division=0)), 4),
        "recall": round(float(recall_score(y_true, pred, zero_division=0)), 4),
        "f1": round(float(f1_score(y_true, pred, zero_division=0)), 4),
        "accuracy": round(float(accuracy_score(y_true, pred)), 4),
        "fpr": round(float(fp / (fp + tn)) if (fp + tn) else 0.0, 4),
        "fnr": round(float(fn / (fn + tp)) if (fn + tp) else 0.0, 4),
        "tp": int(tp),
        "fp": int(fp),
        "tn": int(tn),
        "fn": int(fn),
    }


def tune_threshold(y_true, probs):
    candidates = []
    for threshold in np.arange(0.20, 0.801, 0.01):
        candidates.append(metrics(y_true, probs, float(threshold)))

    # Primary objective: F1.
    # Tie-breaks: higher recall, then lower FPR, then threshold closest to 0.50.
    best = max(
        candidates,
        key=lambda m: (
            m["f1"],
            m["recall"],
            -m["fpr"],
            -abs(m["threshold"] - 0.50),
        ),
    )
    return best, candidates


def make_word_model():
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


def make_char_model():
    return Pipeline([
        ("tfidf", TfidfVectorizer(
            analyzer="char_wb",
            ngram_range=(3, 5),
            lowercase=True,
            sublinear_tf=True,
            min_df=2,
            max_features=100000,
        )),
        ("classifier", LogisticRegression(
            max_iter=1000,
            random_state=42,
        )),
    ])


def main():
    parser = argparse.ArgumentParser(
        description="Train SemanticGuard v2 using LLMBastion train/validation/locked_test splits."
    )
    parser.add_argument(
        "--data-dir",
        default="data/llmbastion_dataset/data",
        help="Directory containing train.jsonl, validation.jsonl, locked_test.jsonl",
    )
    parser.add_argument(
        "--artifact",
        default="app/artifacts/semantic_guard_v2.joblib",
        help="Output path for the selected sklearn Pipeline",
    )
    parser.add_argument(
        "--report",
        default="ml/semantic_guard_v2_report.json",
        help="Output JSON report path",
    )
    args = parser.parse_args()

    data_dir = Path(args.data_dir)
    train_path = data_dir / "train.jsonl"
    val_path = data_dir / "validation.jsonl"
    test_path = data_dir / "locked_test.jsonl"

    for p in [train_path, val_path, test_path]:
        if not p.exists():
            raise FileNotFoundError(f"Missing split file: {p}")

    train_rows, x_train, y_train = load_jsonl(train_path)
    val_rows, x_val, y_val = load_jsonl(val_path)
    test_rows, x_test, y_test = load_jsonl(test_path)

    print(f"Train: {len(train_rows)} | Validation: {len(val_rows)} | Locked test: {len(test_rows)}")
    print("Training candidates: WORD and CHAR")

    candidates = {
        "word": make_word_model(),
        "char": make_char_model(),
    }

    validation_results = {}
    trained_models = {}

    for name, model in candidates.items():
        print(f"\nTraining {name.upper()}...")
        model.fit(x_train, y_train)
        probs = model.predict_proba(x_val)[:, 1]
        best, _ = tune_threshold(y_val, probs)
        validation_results[name] = best
        trained_models[name] = model

        print(
            f"{name.upper()} validation | threshold={best['threshold']:.2f} "
            f"P={best['precision']:.3f} R={best['recall']:.3f} "
            f"F1={best['f1']:.3f} FPR={best['fpr']:.3f}"
        )

    selected_name = max(
        validation_results,
        key=lambda name: (
            validation_results[name]["f1"],
            validation_results[name]["recall"],
            -validation_results[name]["fpr"],
        ),
    )
    selected_model = trained_models[selected_name]
    selected_threshold = validation_results[selected_name]["threshold"]

    print(f"\nSELECTED: {selected_name.upper()} @ threshold={selected_threshold:.2f}")

    # Locked test is intentionally touched only after model + threshold selection.
    test_probs = selected_model.predict_proba(x_test)[:, 1]
    locked_test_result = metrics(y_test, test_probs, selected_threshold)

    print(
        "LOCKED TEST | "
        f"P={locked_test_result['precision']:.3f} "
        f"R={locked_test_result['recall']:.3f} "
        f"F1={locked_test_result['f1']:.3f} "
        f"Acc={locked_test_result['accuracy']:.3f} "
        f"FPR={locked_test_result['fpr']:.3f} "
        f"FNR={locked_test_result['fnr']:.3f}"
    )
    print(
        f"Confusion | TP={locked_test_result['tp']} "
        f"FP={locked_test_result['fp']} "
        f"TN={locked_test_result['tn']} "
        f"FN={locked_test_result['fn']}"
    )

    artifact_path = Path(args.artifact)
    artifact_path.parent.mkdir(parents=True, exist_ok=True)
    joblib.dump(selected_model, artifact_path)

    report = {
        "dataset": {
            "train_rows": len(train_rows),
            "validation_rows": len(val_rows),
            "locked_test_rows": len(test_rows),
        },
        "selection_rule": "Validation F1; tie-break recall, then lower FPR.",
        "validation": validation_results,
        "selected_model": selected_name,
        "selected_threshold": selected_threshold,
        "locked_test": locked_test_result,
        "artifact": str(artifact_path),
        "important_note": (
            "Do not tune the model or threshold using locked_test results. "
            "If the locked test is used for further tuning, it is no longer a locked test."
        ),
    }

    report_path = Path(args.report)
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")

    metadata_path = artifact_path.with_suffix(".metadata.json")
    metadata_path.write_text(
        json.dumps(
            {
                "model": selected_name,
                "threshold": selected_threshold,
                "training_rows": len(train_rows),
                "validation_rows": len(val_rows),
                "locked_test_rows": len(test_rows),
            },
            indent=2,
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    print(f"\nArtifact: {artifact_path}")
    print(f"Metadata: {metadata_path}")
    print(f"Report:   {report_path}")


if __name__ == "__main__":
    main()
