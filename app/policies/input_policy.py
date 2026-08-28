from dataclasses import dataclass
from enum import Enum


DEFAULT_BLOCK_THRESHOLD = 0.50


class PolicyAction(str, Enum):
    ALLOW = "ALLOW"
    BLOCK = "BLOCK"


@dataclass(frozen=True)
class PolicyDecision:
    action: PolicyAction
    score: float
    block_threshold: float | None


class InputPolicy:
    def __init__(self, block_threshold: float = DEFAULT_BLOCK_THRESHOLD):
        if not 0.0 <= block_threshold <= 1.0:
            raise ValueError("block_threshold must be between 0.0 and 1.0")

        self.block_threshold = block_threshold

    def decide(self, score: float) -> PolicyDecision:
        """Backward-compatible single-score policy used by regex evaluation."""

        if not 0.0 <= score <= 1.0:
            raise ValueError("score must be between 0.0 and 1.0")

        action = (
            PolicyAction.BLOCK
            if score >= self.block_threshold
            else PolicyAction.ALLOW
        )

        return PolicyDecision(
            action=action,
            score=score,
            block_threshold=self.block_threshold,
        )

    def decide_assessment(self, assessment) -> PolicyDecision:
        """Map aggregated detector signals to the final action."""

        action = (
            PolicyAction.BLOCK
            if assessment.triggered_detectors
            else PolicyAction.ALLOW
        )

        return PolicyDecision(
            action=action,
            score=assessment.risk_score,
            block_threshold=None,
        )
