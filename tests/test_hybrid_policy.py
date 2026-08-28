from app.policies.input_policy import InputPolicy, PolicyAction
from app.services.risk_engine import RiskEngine


def test_policy_blocks_when_risk_engine_has_signal():
    assessment = RiskEngine().assess(
        rule_score=0.0,
        semantic_score=0.75,
    )

    decision = InputPolicy().decide_assessment(assessment)

    assert decision.action == PolicyAction.BLOCK


def test_policy_allows_when_no_detector_triggers():
    assessment = RiskEngine().assess(
        rule_score=0.10,
        semantic_score=0.20,
    )

    decision = InputPolicy().decide_assessment(assessment)

    assert decision.action == PolicyAction.ALLOW
