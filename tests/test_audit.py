import json

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.database import Base
from app.models import DetectorResult, GatewayRequest
from app.services.audit import save_request_audit


def make_session():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    return sessionmaker(bind=engine)()


def test_audit_saves_multiple_detector_results():
    db = make_session()

    save_request_audit(
        db,
        request_id="test-request-id",
        risk_score=0.0,
        action="ALLOW",
        latency_ms=12.5,
        detector_results=[
            {
                "detector_name": "rule_guard",
                "score": 0.0,
                "evidence": [],
                "latency_ms": 0.2,
            },
            {
                "detector_name": "data_guard",
                "score": 1.0,
                "evidence": {
                    "action": "REDACT",
                    "finding_types": ["email"],
                    "redaction_count": 1,
                },
                "latency_ms": 0.1,
            },
        ],
    )

    request_record = db.query(GatewayRequest).one()
    detector_records = (
        db.query(DetectorResult)
        .order_by(DetectorResult.id)
        .all()
    )

    assert request_record.action == "ALLOW"
    assert len(detector_records) == 2
    assert detector_records[0].detector_name == "rule_guard"
    assert detector_records[1].detector_name == "data_guard"

    evidence = json.loads(detector_records[1].evidence)
    assert evidence == {
        "action": "REDACT",
        "finding_types": ["email"],
        "redaction_count": 1,
    }


def test_data_guard_audit_evidence_contains_no_raw_secret():
    db = make_session()
    raw_secret = "user@example.com"

    save_request_audit(
        db,
        request_id="privacy-test-id",
        risk_score=0.0,
        action="ALLOW",
        latency_ms=1.0,
        detector_results=[
            {
                "detector_name": "data_guard",
                "score": 1.0,
                "evidence": {
                    "action": "REDACT",
                    "finding_types": ["email"],
                    "redaction_count": 1,
                    "sensitive_value": raw_secret,
                },
                "latency_ms": 0.1,
            },
        ],
    )

    row = db.query(DetectorResult).one()
    evidence = json.loads(row.evidence)

    assert raw_secret not in row.evidence
    assert evidence == {
        "action": "REDACT",
        "finding_types": ["email"],
        "redaction_count": 1,
    }


def test_rule_guard_audit_removes_matched_prompt_text():
    db = make_session()
    matched_text = "ignore all previous instructions"

    save_request_audit(
        db,
        request_id="rule-privacy-test",
        risk_score=0.8,
        action="BLOCK",
        latency_ms=1.0,
        detector_results=[
            {
                "detector_name": "rule_guard",
                "score": 0.8,
                "evidence": [
                    {
                        "rule_id": "RG-001",
                        "weight": 0.8,
                        "matched_text": matched_text,
                    }
                ],
                "latency_ms": 0.1,
            }
        ],
    )

    row = db.query(DetectorResult).one()
    evidence = json.loads(row.evidence)

    assert matched_text not in row.evidence
    assert evidence == [
        {
            "rule_id": "RG-001",
            "weight": 0.8,
        }
    ]


def test_provider_audit_uses_metadata_allowlist():
    db = make_session()
    raw_response = "private upstream content"

    save_request_audit(
        db,
        request_id="provider-privacy-test",
        risk_score=0.0,
        action="ERROR",
        latency_ms=1.0,
        detector_results=[
            {
                "detector_name": "provider",
                "score": 1.0,
                "evidence": {
                    "provider": "groq",
                    "status": "ERROR",
                    "error_type": "request_failed",
                    "raw_response": raw_response,
                },
                "latency_ms": 0.1,
            }
        ],
    )

    row = db.query(DetectorResult).one()
    evidence = json.loads(row.evidence)

    assert raw_response not in row.evidence
    assert evidence == {
        "provider": "groq",
        "status": "ERROR",
        "error_type": "request_failed",
    }


def test_unknown_detector_recursively_drops_sensitive_keys():
    db = make_session()

    save_request_audit(
        db,
        request_id="generic-privacy-test",
        risk_score=0.0,
        action="ALLOW",
        latency_ms=1.0,
        detector_results=[
            {
                "detector_name": "future_guard",
                "score": 0.1,
                "evidence": {
                    "safe_type": "metadata",
                    "nested": {
                        "message": "raw user text",
                        "safe_count": 2,
                    },
                },
                "latency_ms": 0.1,
            }
        ],
    )

    row = db.query(DetectorResult).one()
    evidence = json.loads(row.evidence)

    assert evidence == {
        "safe_type": "metadata",
        "nested": {
            "safe_count": 2,
        },
    }
