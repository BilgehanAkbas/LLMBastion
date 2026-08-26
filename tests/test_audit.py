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
                "evidence": ["email"],
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
    assert json.loads(detector_records[1].evidence) == ["email"]
