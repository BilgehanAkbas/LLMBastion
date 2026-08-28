import time
from typing import Annotated
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session
from starlette import status

from ..core.config import GROQ_API_KEY, GROQ_MODEL
from ..database import SessionLocal
from ..guards.input.rule_guard import RuleGuard
from ..guards.input.semantic_guard import SemanticGuard
from ..guards.output.data_guard import DataGuard, OutputAction
from ..policies.input_policy import InputPolicy, PolicyAction
from ..providers.groq_provider import GroqProvider
from ..services.audit import save_request_audit
from ..services.risk_engine import RiskEngine

router = APIRouter(
    prefix="/api/v1",
    tags=["LLMBastion Gateway"],
)

rule_guard = RuleGuard()
semantic_guard = SemanticGuard()
risk_engine = RiskEngine()
input_policy = InputPolicy()
data_guard = DataGuard()
provider = GroqProvider(api_key=GROQ_API_KEY, model=GROQ_MODEL)


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


db_dependency = Annotated[Session, Depends(get_db)]


class ChatRequest(BaseModel):
    message: str = Field(min_length=1, max_length=4000)


class ChatResponse(BaseModel):
    request_id: str
    action: PolicyAction
    risk_score: float
    matched_rules: tuple[str, ...]
    semantic_score: float
    triggered_detectors: tuple[str, ...]
    output_action: OutputAction | None = None
    output_findings: tuple[str, ...] = ()
    response: str | None = None


@router.post("/chat", response_model=ChatResponse)
async def chat(request: ChatRequest, db: db_dependency):
    request_id = str(uuid4())
    request_started = time.perf_counter()

    rule_started = time.perf_counter()
    rule_result = rule_guard.analyze(request.message)
    rule_latency_ms = (
        time.perf_counter() - rule_started
    ) * 1000

    semantic_started = time.perf_counter()
    try:
        semantic_result = semantic_guard.analyze(request.message)
    except RuntimeError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=str(exc),
        ) from exc

    semantic_latency_ms = (
        time.perf_counter() - semantic_started
    ) * 1000

    assessment = risk_engine.assess(
        rule_score=rule_result.score,
        semantic_score=semantic_result.score,
    )
    decision = input_policy.decide_assessment(assessment)

    detector_results = [
        {
            "detector_name": "rule_guard",
            "score": rule_result.score,
            "evidence": [
                {
                    "rule_id": match.rule_id,
                    "weight": match.weight,
                    "matched_text": match.matched_text,
                }
                for match in rule_result.matches
            ],
            "latency_ms": rule_latency_ms,
        },
        {
            "detector_name": "semantic_guard",
            "score": semantic_result.score,
            "evidence": {
                "triggered": (
                    "semantic_guard"
                    in assessment.triggered_detectors
                ),
                "threshold": risk_engine.semantic_threshold,
            },
            "latency_ms": semantic_latency_ms,
        },
    ]

    if decision.action == PolicyAction.BLOCK:
        total_latency_ms = (
            time.perf_counter() - request_started
        ) * 1000

        save_request_audit(
            db,
            request_id=request_id,
            risk_score=assessment.risk_score,
            action=decision.action.value,
            latency_ms=total_latency_ms,
            detector_results=detector_results,
        )

        return ChatResponse(
            request_id=request_id,
            action=decision.action,
            risk_score=assessment.risk_score,
            matched_rules=rule_result.matched_rules,
            semantic_score=semantic_result.score,
            triggered_detectors=assessment.triggered_detectors,
        )

    try:
        model_response = provider.generate(request.message)
    except RuntimeError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=str(exc),
        ) from exc
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="LLM provider request failed",
        ) from exc

    output_guard_started = time.perf_counter()
    output_result = data_guard.analyze(model_response)
    output_guard_latency_ms = (
        time.perf_counter() - output_guard_started
    ) * 1000

    detector_results.append(
        {
            "detector_name": "data_guard",
            "score": 1.0 if output_result.findings else 0.0,
            "evidence": list(output_result.findings),
            "latency_ms": output_guard_latency_ms,
        }
    )

    total_latency_ms = (
        time.perf_counter() - request_started
    ) * 1000

    save_request_audit(
        db,
        request_id=request_id,
        risk_score=assessment.risk_score,
        action=decision.action.value,
        latency_ms=total_latency_ms,
        detector_results=detector_results,
    )

    return ChatResponse(
        request_id=request_id,
        action=decision.action,
        risk_score=assessment.risk_score,
        matched_rules=rule_result.matched_rules,
        semantic_score=semantic_result.score,
        triggered_detectors=assessment.triggered_detectors,
        output_action=output_result.action,
        output_findings=output_result.findings,
        response=output_result.text,
    )
