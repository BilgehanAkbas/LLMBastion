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
from ..guards.output.data_guard import DataGuard, OutputAction
from ..policies.input_policy import InputPolicy, PolicyAction
from ..providers.groq_provider import GroqProvider
from ..services.audit import save_request_audit

router = APIRouter(
    prefix="/api/v1",
    tags=["LLMBastion Gateway"],
)

rule_guard = RuleGuard()
input_policy = InputPolicy(block_threshold=0.70)
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
    output_action: OutputAction | None = None
    output_findings: tuple[str, ...] = ()
    response: str | None = None


@router.post("/chat", response_model=ChatResponse)
async def chat(request: ChatRequest, db: db_dependency):
    request_id = str(uuid4())
    request_started = time.perf_counter()

    input_guard_started = time.perf_counter()
    input_result = rule_guard.analyze(request.message)
    input_guard_latency_ms = (
        time.perf_counter() - input_guard_started
    ) * 1000

    decision = input_policy.decide(input_result.score)

    detector_results = [
        {
            "detector_name": "rule_guard",
            "score": input_result.score,
            "evidence": [
                {
                    "rule_id": match.rule_id,
                    "weight": match.weight,
                    "matched_text": match.matched_text,
                }
                for match in input_result.matches
            ],
            "latency_ms": input_guard_latency_ms,
        }
    ]

    if decision.action == PolicyAction.BLOCK:
        total_latency_ms = (
            time.perf_counter() - request_started
        ) * 1000

        save_request_audit(
            db,
            request_id=request_id,
            risk_score=input_result.score,
            action=decision.action.value,
            latency_ms=total_latency_ms,
            detector_results=detector_results,
        )

        return ChatResponse(
            request_id=request_id,
            action=decision.action,
            risk_score=input_result.score,
            matched_rules=input_result.matched_rules,
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
        risk_score=input_result.score,
        action=decision.action.value,
        latency_ms=total_latency_ms,
        detector_results=detector_results,
    )

    return ChatResponse(
        request_id=request_id,
        action=decision.action,
        risk_score=input_result.score,
        matched_rules=input_result.matched_rules,
        output_action=output_result.action,
        output_findings=output_result.findings,
        response=output_result.text,
    )
