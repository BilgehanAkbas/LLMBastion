import json
from datetime import datetime, timezone

from app.models import DetectorResult
from app.routers.dashboard import _detector_view, _format_dashboard_time


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
        "semantic_guard",
        0.30,
        {"triggered": False, "threshold": 0.40},
    ))

    assert detector["triggered"] is False
    assert detector["threshold"] == 0.40
    assert detector["margin"] == -0.10


def test_semantic_dashboard_view_shows_triggered_score():
    detector = _detector_view(make_detector(
        "semantic_guard",
        0.77,
        {"triggered": True, "threshold": 0.40},
    ))

    assert detector["triggered"] is True
    assert detector["margin"] == 0.37


def test_rule_guard_legacy_evidence_still_works():
    detector = _detector_view(make_detector(
        "rule_guard",
        1.0,
        [{
            "rule_id": "instruction_override",
            "weight": 0.55,
            "matched_text": "ignore previous instructions",
        }],
    ))

    assert detector["triggered"] is True
    assert detector["threshold"] == 0.50
    assert len(detector["findings"]) == 1


def test_data_guard_structured_evidence_is_rendered():
    detector = _detector_view(make_detector(
        "data_guard",
        1.0,
        {
            "action": "REDACT",
            "finding_types": [
                "email",
                "turkish_iban",
            ],
            "redaction_count": 3,
        },
    ))

    assert detector["threshold"] is None
    assert detector["triggered"] is False
    assert detector["output_action"] == "REDACT"
    assert detector["redaction_count"] == 3
    assert detector["findings"] == [
        "email",
        "turkish_iban",
    ]


def test_data_guard_legacy_list_evidence_still_works():
    detector = _detector_view(make_detector(
        "data_guard",
        1.0,
        ["email"],
    ))

    assert detector["triggered"] is False
    assert detector["findings"] == ["email"]
    assert detector["redaction_count"] == 1


def test_dashboard_time_converts_utc_to_turkey_time():
    value = datetime(
        2026, 9, 1, 9, 29, 51,
        tzinfo=timezone.utc,
    )

    assert _format_dashboard_time(value) == "2026-09-01 12:29:51"


def test_dashboard_time_treats_sqlite_naive_value_as_utc():
    value = datetime(2026, 9, 1, 9, 29, 51)

    assert _format_dashboard_time(value) == "2026-09-01 12:29:51"


def test_provider_dashboard_view_reads_success_metadata():
    detector = _detector_view(make_detector(
        "provider",
        0.0,
        {
            "provider": "groq",
            "status": "SUCCESS",
        },
    ))

    assert detector["triggered"] is False
    assert detector["threshold"] is None
    assert detector["provider_name"] == "groq"
    assert detector["provider_status"] == "SUCCESS"
    assert detector["provider_error_type"] is None


def test_provider_dashboard_view_reads_error_metadata():
    detector = _detector_view(make_detector(
        "provider",
        1.0,
        {
            "provider": "groq",
            "status": "ERROR",
            "error_type": "request_failed",
        },
    ))

    assert detector["triggered"] is False
    assert detector["provider_status"] == "ERROR"
    assert detector["provider_error_type"] == "request_failed"
