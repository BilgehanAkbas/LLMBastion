import pytest

from app.policies.input_policy import InputPolicy, PolicyAction


def test_low_risk_is_allowed():
    policy = InputPolicy(block_threshold=0.70)

    decision = policy.decide(0.55)

    assert decision.action == PolicyAction.ALLOW


def test_threshold_is_blocked():
    policy = InputPolicy(block_threshold=0.70)

    decision = policy.decide(0.70)

    assert decision.action == PolicyAction.BLOCK


def test_high_risk_is_blocked():
    policy = InputPolicy(block_threshold=0.70)

    decision = policy.decide(1.0)

    assert decision.action == PolicyAction.BLOCK


def test_invalid_score_is_rejected():
    policy = InputPolicy()

    with pytest.raises(ValueError):
        policy.decide(1.20)


def test_invalid_threshold_is_rejected():
    with pytest.raises(ValueError):
        InputPolicy(block_threshold=-0.10)
