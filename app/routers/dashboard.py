import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.templating import Jinja2Templates
from sqlalchemy import func
from sqlalchemy.orm import Session

from ..database import SessionLocal
from ..models import DetectorResult, GatewayRequest
from ..policies.input_policy import DEFAULT_BLOCK_THRESHOLD
from ..services.risk_engine import DEFAULT_SEMANTIC_THRESHOLD

router = APIRouter(tags=["Dashboard"])
BASE_DIR = Path(__file__).resolve().parent.parent
templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))
TURKEY_TIMEZONE = timezone(timedelta(hours=3))


def _format_dashboard_time(value: datetime | None) -> str:
    """Format stored UTC timestamps for the Turkey-facing dashboard."""
    if value is None:
        return "—"
    if value.tzinfo is None:
        # SQLite commonly returns timezone-aware columns as naive datetimes.
        # GatewayRequest.created_at is written in UTC, so restore that context.
        value = value.replace(tzinfo=timezone.utc)
    local_value = value.astimezone(TURKEY_TIMEZONE)
    return local_value.strftime("%Y-%m-%d %H:%M:%S")


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def _parse_evidence(raw):
    if raw is None:
        return []
    if isinstance(raw, (list, dict)):
        return raw
    try:
        return json.loads(raw)
    except (TypeError, json.JSONDecodeError):
        return [str(raw)]


def _threshold_for(detector_name: str) -> float | None:
    if detector_name == "rule_guard":
        return DEFAULT_BLOCK_THRESHOLD
    if detector_name == "semantic_guard":
        return DEFAULT_SEMANTIC_THRESHOLD
    return None


def _detector_view(row: DetectorResult) -> dict:
    evidence = _parse_evidence(row.evidence)
    threshold = _threshold_for(row.detector_name)

    if row.detector_name == "data_guard":
        # DataGuard protects output after the input decision. Its findings must
        # never be reconstructed as input-policy triggers.
        triggered = False
        findings = (
            evidence.get("finding_types", [])
            if isinstance(evidence, dict)
            else evidence if isinstance(evidence, list) else []
        )
        output_action = (
            evidence.get("action")
            if isinstance(evidence, dict)
            else None
        )
        redaction_count = (
            evidence.get("redaction_count", len(findings))
            if isinstance(evidence, dict)
            else len(findings)
        )
    else:
        if isinstance(evidence, dict):
            stored_triggered = evidence.get("triggered")
            stored_threshold = evidence.get("threshold")
            if isinstance(stored_threshold, (int, float)):
                threshold = float(stored_threshold)
            if isinstance(stored_triggered, bool):
                triggered = stored_triggered
            else:
                triggered = (
                    threshold is not None
                    and row.score >= threshold
                )
        else:
            triggered = (
                threshold is not None
                and row.score >= threshold
            )

        if row.detector_name == "rule_guard":
            if isinstance(evidence, dict):
                findings = evidence.get("matches", [])
            else:
                findings = (
                    evidence
                    if isinstance(evidence, list)
                    else []
                )
        else:
            findings = []

        output_action = None
        redaction_count = 0

    margin = (
        None
        if threshold is None
        else round(row.score - threshold, 4)
    )

    return {
        "name": row.detector_name,
        "score": row.score,
        "latency_ms": row.latency_ms,
        "evidence": evidence,
        "findings": findings,
        "threshold": threshold,
        "triggered": triggered,
        "margin": margin,
        "output_action": output_action,
        "redaction_count": redaction_count,
    }


def _request_detector_map(rows):
    result = {}
    for row in rows:
        result.setdefault(
            row.request_id, {}
        )[row.detector_name] = _detector_view(row)
    return result


@router.get("/dashboard")
def dashboard(
    request: Request,
    db: Session = Depends(get_db),
):
    total_requests = (
        db.query(func.count(GatewayRequest.id)).scalar()
        or 0
    )
    allowed_requests = (
        db.query(func.count(GatewayRequest.id))
        .filter(GatewayRequest.action == "ALLOW")
        .scalar()
        or 0
    )
    blocked_requests = (
        db.query(func.count(GatewayRequest.id))
        .filter(GatewayRequest.action == "BLOCK")
        .scalar()
        or 0
    )
    data_guard_findings = (
        db.query(func.count(DetectorResult.id))
        .filter(
            DetectorResult.detector_name == "data_guard",
            DetectorResult.score > 0,
        )
        .scalar()
        or 0
    )
    average_latency = (
        db.query(func.avg(GatewayRequest.latency_ms)).scalar()
        or 0.0
    )

    recent_requests = (
        db.query(GatewayRequest)
        .order_by(GatewayRequest.created_at.desc())
        .limit(20)
        .all()
    )
    recent_ids = [
        item.request_id
        for item in recent_requests
    ]

    detector_rows = []
    if recent_ids:
        detector_rows = (
            db.query(DetectorResult)
            .filter(
                DetectorResult.request_id.in_(recent_ids)
            )
            .all()
        )
    detector_map = _request_detector_map(detector_rows)

    recent_items = []
    semantic_only_blocks = 0
    for item in recent_requests:
        detectors = detector_map.get(item.request_id, {})
        rule = detectors.get("rule_guard")
        semantic = detectors.get("semantic_guard")
        triggered = []

        if rule and rule["triggered"]:
            triggered.append("RuleGuard")
        if semantic and semantic["triggered"]:
            triggered.append("SemanticGuard")

        if (
            item.action == "BLOCK"
            and semantic
            and semantic["triggered"]
            and not (rule and rule["triggered"])
        ):
            semantic_only_blocks += 1

        recent_items.append({
            "request": item,
            "rule_score": (
                None if rule is None else rule["score"]
            ),
            "semantic_score": (
                None
                if semantic is None
                else semantic["score"]
            ),
            "triggered_by": triggered,
            "created_at_display": _format_dashboard_time(item.created_at),
        })

    blocked_rate = (
        blocked_requests / total_requests * 100
        if total_requests
        else 0.0
    )

    return templates.TemplateResponse(
        "dashboard.html",
        {
            "request": request,
            "total_requests": total_requests,
            "allowed_requests": allowed_requests,
            "blocked_requests": blocked_requests,
            "blocked_rate": blocked_rate,
            "semantic_only_blocks_recent": (
                semantic_only_blocks
            ),
            "data_guard_findings": data_guard_findings,
            "average_latency_ms": average_latency,
            "recent_items": recent_items,
            "rule_threshold": DEFAULT_BLOCK_THRESHOLD,
            "semantic_threshold": DEFAULT_SEMANTIC_THRESHOLD,
        },
    )


@router.get("/dashboard/requests/{request_id}")
def request_detail(
    request_id: str,
    request: Request,
    db: Session = Depends(get_db),
):
    gateway_request = (
        db.query(GatewayRequest)
        .filter(GatewayRequest.request_id == request_id)
        .first()
    )
    if gateway_request is None:
        raise HTTPException(
            status_code=404,
            detail="Request not found",
        )

    rows = (
        db.query(DetectorResult)
        .filter(DetectorResult.request_id == request_id)
        .order_by(DetectorResult.id.asc())
        .all()
    )
    detectors = [
        _detector_view(row)
        for row in rows
    ]
    detector_map = {
        detector["name"]: detector
        for detector in detectors
    }
    triggered_detectors = [
        detector["name"]
        for detector in detectors
        if (
            detector["name"] != "data_guard"
            and detector["triggered"]
        )
    ]

    detector_latency_ms = sum(
        detector["latency_ms"]
        for detector in detectors
    )
    other_latency_ms = max(
        gateway_request.latency_ms
        - detector_latency_ms,
        0.0,
    )
    provider_called = "data_guard" in detector_map

    if gateway_request.action == "BLOCK":
        if triggered_detectors:
            decision_reason = (
                "Blocked because "
                + ", ".join(triggered_detectors)
                + " crossed its configured threshold."
            )
        else:
            decision_reason = (
                "Blocked by policy, but no current detector "
                "threshold match could be reconstructed "
                "from audit data."
            )
    else:
        decision_reason = (
            "Allowed because no input detector crossed "
            "its configured threshold."
        )

    return templates.TemplateResponse(
        "request_detail.html",
        {
            "request": request,
            "gateway_request": gateway_request,
            "detectors": detectors,
            "detector_map": detector_map,
            "triggered_detectors": triggered_detectors,
            "provider_called": provider_called,
            "detector_latency_ms": detector_latency_ms,
            "other_latency_ms": other_latency_ms,
            "decision_reason": decision_reason,
            "created_at_display": _format_dashboard_time(
                gateway_request.created_at
            ),
        },
    )
