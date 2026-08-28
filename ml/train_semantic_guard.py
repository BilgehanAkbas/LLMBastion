from __future__ import annotations

import json
import sys
from pathlib import Path

import joblib

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.services.risk_engine import DEFAULT_SEMANTIC_THRESHOLD
from ml.public_benchmark_slabs import DATASET_NAME, load_public_dataset, to_rows
from ml.train_and_compare import build_model


MODEL_DIR = PROJECT_ROOT / "app" / "artifacts"
MODEL_PATH = MODEL_DIR / "semantic_guard.joblib"
META_PATH = MODEL_DIR / "semantic_guard_meta.json"


def main() -> None:
    dataset = load_public_dataset()
    train_rows = to_rows(dataset["train"])

    model = build_model()
    model.fit(
        [row["text"] for row in train_rows],
        [1 if row["label"] == "attack" else 0 for row in train_rows],
    )

    MODEL_DIR.mkdir(parents=True, exist_ok=True)
    joblib.dump(model, MODEL_PATH)

    metadata = {
        "model": "TF-IDF + LogisticRegression",
        "dataset": DATASET_NAME,
        "training_split": "train",
        "training_rows": len(train_rows),
        "semantic_threshold": DEFAULT_SEMANTIC_THRESHOLD,
        "threshold_source": "clean validation benchmark",
    }

    META_PATH.write_text(
        json.dumps(metadata, indent=2),
        encoding="utf-8",
    )

    print(f"Saved model: {MODEL_PATH}")
    print(f"Saved metadata: {META_PATH}")
    print(
        f"Semantic threshold: {DEFAULT_SEMANTIC_THRESHOLD:.2f}"
    )


if __name__ == "__main__":
    main()
