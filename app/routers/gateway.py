import time
from typing import Annotated
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException
from langchain_core.messages import HumanMessage
from langchain_google_genai import ChatGoogleGenerativeAI
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session
from starlette import status

from ..core.config import GEMINI_MODEL, GOOGLE_API_KEY
from ..database import SessionLocal
from ..guards.input.rule_guard import RuleGuard
from ..guards.output.data_guard import DataGuard, OutputAction
from ..policies.input_policy import InputPolicy, PolicyAction
from ..services.audit import save_request_audit


router = APIRouter(
    prefix="/api/v1",
    tags=["LLMBastion Gateway"],
)

rule_guard = RuleGuard()
input_policy = InputPolicy(block_threshold=0.70)
data_guard = DataGuard()


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


def ask_gemini(message: str) -> str:
    if not GOOGLE_API_KEY:
        raise RuntimeError("GOOGLE_API_KEY is not configured")

    llm = ChatGoogleGenerativeAI(
        model=GEMINI_MODEL,
        google_api_key=GOOGLE_API_KEY,
    )

    result = llm.invoke([HumanMessage(content=message)])
    return str(result.content)


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

    input_evidence = [
        {
            "rule_id": match.rule_id,
            "weight": match.weight,
            "matched_text": match.matched_text,
        }
        for match in input_result.matches
    ]

    detector_results = [
        {
            "detector_name": "rule_guard",
            "score": input_result.score,
            "evidence": input_evidence,
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
            response=None,
        )

    try:
        model_response = ask_gemini(request.message)
    except RuntimeError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=str(exc),
        ) from exc
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Gemini request failed",
        ) from exc

    output_guard_started = time.perf_counter()
    output_result = data_guard.analyze(model_response)
    output_guard_latency_ms = (
        time.perf_counter() - output_guard_started
    ) * 1000

    detector_results.append(
        {
            "detector_name": "data_guard",
            # Binary detection signal, not a probability.
            "score": 1.0 if output_result.findings else 0.0,
            # Store only finding TYPES, never the sensitive values themselves.
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
