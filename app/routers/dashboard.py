from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, Depends, Request
from fastapi.templating import Jinja2Templates
from sqlalchemy import func
from sqlalchemy.orm import Session

from ..database import SessionLocal
from ..models import DetectorResult, GatewayRequest

router = APIRouter(tags=["Dashboard"])

TEMPLATES_DIR = Path(__file__).resolve().parents[1] / "templates"
templates = Jinja2Templates(directory=str(TEMPLATES_DIR))


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


db_dependency = Annotated[Session, Depends(get_db)]


@router.get("/dashboard")
async def dashboard(request: Request, db: db_dependency):
    total_requests = db.query(func.count(GatewayRequest.id)).scalar() or 0

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

    average_latency_ms = (
        db.query(func.avg(GatewayRequest.latency_ms)).scalar() or 0.0
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

    recent_requests = (
        db.query(GatewayRequest)
        .order_by(GatewayRequest.created_at.desc())
        .limit(20)
        .all()
    )

    return templates.TemplateResponse(
        "dashboard.html",
        {
            "request": request,
            "user": None,
            "total_requests": total_requests,
            "allowed_requests": allowed_requests,
            "blocked_requests": blocked_requests,
            "data_guard_findings": data_guard_findings,
            "average_latency_ms": round(float(average_latency_ms), 2),
            "recent_requests": recent_requests,
        },
    )
