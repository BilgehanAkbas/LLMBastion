from __future__ import annotations

from dataclasses import dataclass

from ..policies.input_policy import DEFAULT_BLOCK_THRESHOLD


DEFAULT_SEMANTIC_THRESHOLD = 0.40


@dataclass(frozen=True)
class RiskAssessment:
    risk_score: float
    triggered_detectors: tuple[str, ...]
    rule_score: float
    semantic_score: float


class RiskEngine:
    """Aggregate detector signals using the tested OR strategy."""

    def __init__(
        self,
        *,
        rule_threshold: float = DEFAULT_BLOCK_THRESHOLD,
        semantic_threshold: float = DEFAULT_SEMANTIC_THRESHOLD,
    ):
        for name, value in (
            ("rule_threshold", rule_threshold),
            ("semantic_threshold", semantic_threshold),
        ):
            if not 0.0 <= value <= 1.0:
                raise ValueError(f"{name} must be between 0.0 and 1.0")

        self.rule_threshold = rule_threshold
        self.semantic_threshold = semantic_threshold

    def assess(
        self,
        *,
        rule_score: float,
        semantic_score: float,
    ) -> RiskAssessment:
        for name, value in (
            ("rule_score", rule_score),
            ("semantic_score", semantic_score),
        ):
            if not 0.0 <= value <= 1.0:
                raise ValueError(f"{name} must be between 0.0 and 1.0")

        triggered = []

        if rule_score >= self.rule_threshold:
            triggered.append("rule_guard")

        if semantic_score >= self.semantic_threshold:
            triggered.append("semantic_guard")

        return RiskAssessment(
            risk_score=round(max(rule_score, semantic_score), 4),
            triggered_detectors=tuple(triggered),
            rule_score=rule_score,
            semantic_score=semantic_score,
        )
