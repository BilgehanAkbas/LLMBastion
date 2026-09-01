import json
from typing import Any

from sqlalchemy.orm import Session

from ..models import DetectorResult, GatewayRequest


_SENSITIVE_EVIDENCE_KEYS = frozenset({
    "matched_text",
    "raw_prompt",
    "prompt",
    "message",
    "raw_response",
    "response",
    "content",
    "sensitive_value",
    "secret",
    "api_key",
    "authorization",
    "password",
})


def _sanitize_generic_evidence(value: Any) -> Any:
    """Recursively remove known raw/sensitive payload fields."""
    if isinstance(value, dict):
        return {
            key: _sanitize_generic_evidence(item)
            for key, item in value.items()
            if str(key).lower() not in _SENSITIVE_EVIDENCE_KEYS
        }

    if isinstance(value, (list, tuple)):
        return [
            _sanitize_generic_evidence(item)
            for item in value
        ]

    return value


def _sanitize_detector_evidence(
    detector_name: str,
    evidence: Any,
) -> Any:
    """Keep only metadata required for known detector audit records."""
    if detector_name == "rule_guard":
        if not isinstance(evidence, (list, tuple)):
            return []

        sanitized = []
        for item in evidence:
            if not isinstance(item, dict):
                continue

            metadata = {}
            if "rule_id" in item:
                metadata["rule_id"] = item["rule_id"]
            if "weight" in item:
                metadata["weight"] = item["weight"]

            if metadata:
                sanitized.append(metadata)

        return sanitized

    if detector_name == "semantic_guard":
        if not isinstance(evidence, dict):
            return {}

        return {
            key: evidence[key]
            for key in ("triggered", "threshold")
            if key in evidence
        }

    if detector_name == "provider":
        if not isinstance(evidence, dict):
            return {}

        return {
            key: evidence[key]
            for key in (
                "provider",
                "status",
                "error_type",
            )
            if key in evidence
        }

    if detector_name == "data_guard":
        if not isinstance(evidence, dict):
            return {}

        return {
            key: evidence[key]
            for key in (
                "action",
                "finding_types",
                "redaction_count",
            )
            if key in evidence
        }

    return _sanitize_generic_evidence(evidence)


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
                _sanitize_detector_evidence(
                    result["detector_name"],
                    result["evidence"],
                ),
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
