from app.services.risk_engine import RiskEngine


def test_semantic_signal_can_trigger_hybrid_risk():
    result = RiskEngine().assess(
        rule_score=0.0,
        semantic_score=0.70,
    )

    assert result.triggered_detectors == ("semantic_guard",)
    assert result.risk_score == 0.70


def test_rule_signal_can_trigger_hybrid_risk():
    result = RiskEngine().assess(
        rule_score=0.65,
        semantic_score=0.10,
    )

    assert result.triggered_detectors == ("rule_guard",)
    assert result.risk_score == 0.65


def test_both_detectors_can_trigger():
    result = RiskEngine().assess(
        rule_score=0.80,
        semantic_score=0.90,
    )

    assert result.triggered_detectors == (
        "rule_guard",
        "semantic_guard",
    )
    assert result.risk_score == 0.90
