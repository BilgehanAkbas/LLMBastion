import json

from sqlalchemy.orm import Session

from ..models import DetectorResult, GatewayRequest


def save_request_audit(
    db: Session,
    *,
    request_id: str,
    risk_score: float,
    action: str,
    latency_ms: float,
    detector_results: list[dict],
) -> None:
    request_record = GatewayRequest(
        request_id=request_id,
        risk_score=risk_score,
        action=action,
        latency_ms=latency_ms,
    )

    detector_records = [
        DetectorResult(
            request_id=request_id,
            detector_name=result["detector_name"],
            score=result["score"],
            evidence=json.dumps(
                result["evidence"],
                ensure_ascii=False,
            ),
            latency_ms=result["latency_ms"],
        )
        for result in detector_results
    ]

    try:
        db.add(request_record)
        db.flush()
        db.add_all(detector_records)
        db.commit()
    except Exception:
        db.rollback()
        raise
