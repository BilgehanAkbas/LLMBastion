from __future__ import annotations

import argparse
import json
from pathlib import Path

import joblib
import numpy as np
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.linear_model import LogisticRegression
from sklearn.pipeline import Pipeline


def load_training_data(path: Path) -> tuple[list[str], np.ndarray]:
    rows = [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]

    texts = [row["text"] for row in rows]
    labels = np.array(
        [1 if row["label"] == "attack" else 0 for row in rows],
        dtype=int,
    )
    return texts, labels


def build_selected_model() -> Pipeline:
    """Reproduce the WORD model selected during SemanticGuard v2 validation."""
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


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Build the frozen SemanticGuard v2 runtime artifact from train.jsonl only. "
            "This script does not read validation.jsonl or locked_test.jsonl."
        )
    )
    parser.add_argument(
        "--train",
        default="data/llmbastion_dataset/data/train.jsonl",
        help="Path to the frozen SemanticGuard v2 training split.",
    )
    parser.add_argument(
        "--artifact",
        default="app/artifacts/semantic_guard_v2.joblib",
        help="Output path for the selected sklearn pipeline.",
    )
    args = parser.parse_args()

    train_path = Path(args.train)
    if not train_path.exists():
        raise FileNotFoundError(f"Training split not found: {train_path}")

    texts, labels = load_training_data(train_path)
    model = build_selected_model()
    model.fit(texts, labels)

    artifact_path = Path(args.artifact)
    artifact_path.parent.mkdir(parents=True, exist_ok=True)
    joblib.dump(model, artifact_path)

    print(f"SemanticGuard v2 runtime artifact built from {len(texts)} training rows.")
    print(f"Artifact: {artifact_path}")
    print("Runtime threshold remains fixed at 0.51 in RiskEngine.")


if __name__ == "__main__":
    main()
