from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

import joblib
import sklearn


DEFAULT_MODEL_PATH = Path(
    "app/artifacts/semantic_guard_v2.joblib"
)
ARTIFACT_FORMAT_VERSION = 1
SEMANTIC_GUARD_VERSION = "v2"


@dataclass(frozen=True)
class SemanticGuardResult:
    score: float


class SemanticGuard:
    """ML detector that returns an attack probability only."""

    def __init__(
        self,
        model_path: str | Path = DEFAULT_MODEL_PATH,
    ):
        self.model_path = Path(model_path)
        self._model = None

    @property
    def metadata_path(self) -> Path:
        return self.model_path.with_suffix(".meta.json")

    def _load_metadata(self) -> dict:
        if not self.metadata_path.exists():
            raise RuntimeError(
                "SemanticGuard artifact metadata not found. "
                "Activate the project virtual environment and run: "
                "python ml/build_semantic_guard_v2_artifact.py"
            )

        try:
            metadata = json.loads(
                self.metadata_path.read_text(
                    encoding="utf-8"
                )
            )
        except (OSError, json.JSONDecodeError) as exc:
            raise RuntimeError(
                "SemanticGuard artifact metadata is invalid. "
                "Rebuild it with: "
                "python ml/build_semantic_guard_v2_artifact.py"
            ) from exc

        if not isinstance(metadata, dict):
            raise RuntimeError(
                "SemanticGuard artifact metadata must be a JSON object."
            )

        return metadata

    def _validate_runtime_compatibility(self) -> None:
        metadata = self._load_metadata()

        artifact_format = metadata.get("artifact_format")
        if artifact_format != ARTIFACT_FORMAT_VERSION:
            raise RuntimeError(
                "Unsupported SemanticGuard artifact format: "
                f"{artifact_format!r}. Rebuild the runtime artifact."
            )

        guard_version = metadata.get(
            "semantic_guard_version"
        )
        if guard_version != SEMANTIC_GUARD_VERSION:
            raise RuntimeError(
                "SemanticGuard artifact version mismatch: "
                f"artifact={guard_version!r}, "
                f"runtime={SEMANTIC_GUARD_VERSION!r}. "
                "Rebuild the runtime artifact."
            )

        artifact_sklearn = metadata.get(
            "scikit_learn_version"
        )
        runtime_sklearn = sklearn.__version__

        if not isinstance(artifact_sklearn, str):
            raise RuntimeError(
                "SemanticGuard artifact metadata does not contain "
                "a valid scikit_learn_version. Rebuild the artifact."
            )

        if artifact_sklearn != runtime_sklearn:
            raise RuntimeError(
                "SemanticGuard scikit-learn version mismatch: "
                f"artifact={artifact_sklearn}, "
                f"runtime={runtime_sklearn}. "
                "Activate the project .venv, install requirements, "
                "and rebuild with: "
                "python ml/build_semantic_guard_v2_artifact.py"
            )

    def _load_model(self):
        if self._model is not None:
            return self._model

        if not self.model_path.exists():
            raise RuntimeError(
                "SemanticGuard model artifact not found. "
                "Run: python ml/build_semantic_guard_v2_artifact.py"
            )

        # Validate metadata before unpickling the sklearn artifact.
        # This prevents known incompatible sklearn versions from
        # reaching inference and failing with opaque AttributeErrors.
        self._validate_runtime_compatibility()

        try:
            self._model = joblib.load(self.model_path)
        except Exception as exc:
            raise RuntimeError(
                "SemanticGuard model artifact could not be loaded. "
                "Rebuild it in the active project environment with: "
                "python ml/build_semantic_guard_v2_artifact.py"
            ) from exc

        if not hasattr(self._model, "predict_proba"):
            raise RuntimeError(
                "SemanticGuard model must implement predict_proba()."
            )

        return self._model

    def analyze(self, text: str) -> SemanticGuardResult:
        if not isinstance(text, str):
            raise TypeError(
                "SemanticGuard input must be a string"
            )

        model = self._load_model()
        attack_probability = float(
            model.predict_proba([text])[0][1]
        )

        return SemanticGuardResult(
            score=round(attack_probability, 4),
        )
