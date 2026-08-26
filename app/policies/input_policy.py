from dataclasses import dataclass
from enum import Enum


class PolicyAction(str, Enum):
    ALLOW = "ALLOW"
    BLOCK = "BLOCK"


@dataclass(frozen=True)
class PolicyDecision:
    action: PolicyAction
    score: float
    block_threshold: float


class InputPolicy:
    def __init__(self, block_threshold: float = 0.70):
        if not 0.0 <= block_threshold <= 1.0:
            raise ValueError("block_threshold must be between 0.0 and 1.0")

        self.block_threshold = block_threshold

    def decide(self, score: float) -> PolicyDecision:
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
