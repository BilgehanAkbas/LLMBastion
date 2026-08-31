from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import joblib


DEFAULT_MODEL_PATH = Path("app/artifacts/semantic_guard_v2.joblib")


@dataclass(frozen=True)
class SemanticGuardResult:
    score: float


class SemanticGuard:
    """ML detector that returns an attack probability only."""

    def __init__(self, model_path: str | Path = DEFAULT_MODEL_PATH):
        self.model_path = Path(model_path)
        self._model = None

    def _load_model(self):
        if self._model is not None:
            return self._model

        if not self.model_path.exists():
            raise RuntimeError(
                "SemanticGuard model artifact not found. "
                "Run: python ml/train_semantic_guard_v2.py"
            )

        self._model = joblib.load(self.model_path)

        if not hasattr(self._model, "predict_proba"):
            raise RuntimeError(
                "SemanticGuard model must implement predict_proba()."
            )

        return self._model

    def analyze(self, text: str) -> SemanticGuardResult:
        if not isinstance(text, str):
            raise TypeError("SemanticGuard input must be a string")

        model = self._load_model()
        attack_probability = float(
            model.predict_proba([text])[0][1]
        )

        return SemanticGuardResult(
            score=round(attack_probability, 4),
        )
