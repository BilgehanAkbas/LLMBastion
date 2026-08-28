import json

from app.models import DetectorResult
from app.routers.dashboard import _detector_view


def make_detector(name, score, evidence):
    return DetectorResult(
        request_id="request-1",
        detector_name=name,
        score=score,
        evidence=json.dumps(evidence),
        latency_ms=1.0,
    )


def test_semantic_dashboard_view_reads_triggered_boolean():
    detector = _detector_view(make_detector(
        "semantic_guard", 0.30,
        {"triggered": False, "threshold": 0.40},
    ))
    assert detector["triggered"] is False
    assert detector["threshold"] == 0.40
    assert detector["margin"] == -0.10


def test_semantic_dashboard_view_shows_triggered_score():
    detector = _detector_view(make_detector(
        "semantic_guard", 0.77,
        {"triggered": True, "threshold": 0.40},
    ))
    assert detector["triggered"] is True
    assert detector["margin"] == 0.37


def test_rule_guard_legacy_evidence_still_works():
    detector = _detector_view(make_detector(
        "rule_guard", 1.0,
        [{"rule_id": "instruction_override", "weight": 0.55, "matched_text": "ignore previous instructions"}],
    ))
    assert detector["triggered"] is True
    assert detector["threshold"] == 0.50
    assert len(detector["findings"]) == 1
