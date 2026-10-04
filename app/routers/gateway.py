import asyncio
import logging
import time
from typing import Annotated
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session
from starlette import status
from groq import APITimeoutError

from ..core.config import (
    GROQ_API_KEY,
    GROQ_MODEL,
    GROQ_MAX_RETRIES,
    GROQ_TIMEOUT_SECONDS,
    GROQ_TOTAL_DEADLINE_SECONDS,
    GROQ_MAX_CONCURRENT_REQUESTS,
    GROQ_MAX_QUEUED_REQUESTS,
    LLM_PROVIDER,
)
from ..core.observability import get_request_id, log_event
from ..database import SessionLocal
from ..guards.input.rule_guard import RuleGuard
from ..guards.input.semantic_guard import SemanticGuard
from ..guards.input.benign_intent import adapt_semantic_signal
from ..guards.output.data_guard import DataGuard, OutputAction
from ..policies.input_policy import InputPolicy, PolicyAction
from ..providers.errors import (
    ProviderConfigurationError,
    ProviderResponseError,
    ProviderOverloadedError,
)
from ..providers.admission import ProviderAdmission
from ..providers.factory import build_provider
from ..services.audit import save_request_audit
from ..services.risk_engine import RiskEngine

logger = logging.getLogger(__name__)


router = APIRouter(
    prefix="/api/v1",
    tags=["LLMBastion Gateway"],
)

rule_guard = RuleGuard()
semantic_guard = SemanticGuard()
risk_engine = RiskEngine()
input_policy = InputPolicy()
data_guard = DataGuard()
provider = build_provider(
    LLM_PROVIDER,
    groq_api_key=GROQ_API_KEY,
    groq_model=GROQ_MODEL,
    groq_timeout_seconds=GROQ_TIMEOUT_SECONDS,
    groq_max_retries=GROQ_MAX_RETRIES,
)
provider_admission = ProviderAdmission(GROQ_MAX_CONCURRENT_REQUESTS, GROQ_MAX_QUEUED_REQUESTS)


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
    output_redaction_count: int = 0
    response: str | None = None


@router.post("/chat", response_model=ChatResponse)
async def chat(request: ChatRequest, db: db_dependency):
    request_id = get_request_id() or str(uuid4())
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
        semantic_latency_ms = (
            time.perf_counter() - semantic_started
        ) * 1000
        log_event(
            logger,
            logging.ERROR,
            "semantic_guard.unavailable",
            latency_ms=round(semantic_latency_ms, 3),
            exc_info=(
                type(exc),
                exc,
                exc.__traceback__,
            ),
        )
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=str(exc),
        ) from exc

    semantic_latency_ms = (
        time.perf_counter() - semantic_started
    ) * 1000

    semantic_signal = adapt_semantic_signal(
        request.message, rule_result, semantic_result.score, risk_engine.semantic_threshold,
    )
    assessment = risk_engine.assess(
        rule_score=rule_result.score,
        semantic_score=semantic_signal.effective_score,
    )
    decision = input_policy.decide_assessment(assessment)

    provider_called = False

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
                **semantic_signal.evidence,
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
        log_event(
            logger,
            logging.INFO,
            "gateway.decision",
            action=decision.action.value,
            risk_score=round(assessment.risk_score, 4),
            semantic_score=round(semantic_result.score, 4),
            duration_ms=round(total_latency_ms, 3),
        )

        return ChatResponse(
            request_id=request_id,
            action=decision.action,
            risk_score=assessment.risk_score,
            matched_rules=rule_result.matched_rules,
            semantic_score=semantic_result.score,
            triggered_detectors=assessment.triggered_detectors,
        )

    provider_started = time.perf_counter()
    provider_deadline = asyncio.timeout(GROQ_TOTAL_DEADLINE_SECONDS)

    try:
        # Covers admission, client setup, network waits and the retry chain.
        # Cancellation propagates directly to async SDK/HTTPX I/O.
        async with provider_deadline:
            async with provider_admission.slot():
                # Do not dispatch after expiry even if the timer callback is
                # delayed behind a semaphore handoff on a busy event loop.
                if asyncio.get_running_loop().time() >= provider_deadline.when():
                    raise TimeoutError
                provider_called = True
                model_response = await provider.generate(request.message)
    except ProviderConfigurationError as exc:
        provider_latency_ms = (
            time.perf_counter() - provider_started
        ) * 1000
        detector_results.append({
            "detector_name": "provider",
            "score": 1.0,
            "evidence": {
                "provider": LLM_PROVIDER,
                "status": "ERROR",
                "error_type": "configuration",
            },
            "latency_ms": provider_latency_ms,
        })
        log_event(
            logger,
            logging.ERROR,
            "provider.complete",
            provider=LLM_PROVIDER,
            provider_status="error",
            error_type="configuration",
            latency_ms=round(provider_latency_ms, 3),
            exc_info=(
                type(exc),
                exc,
                exc.__traceback__,
            ),
        )
        total_latency_ms = (
            time.perf_counter() - request_started
        ) * 1000
        save_request_audit(
            db,
            request_id=request_id,
            risk_score=assessment.risk_score,
            action="ERROR",
            latency_ms=total_latency_ms,
            detector_results=detector_results,
        )
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=str(exc),
        ) from exc
    except ProviderResponseError as exc:
        provider_latency_ms = (
            time.perf_counter() - provider_started
        ) * 1000
        detector_results.append({
            "detector_name": "provider",
            "score": 1.0,
            "evidence": {
                "provider": LLM_PROVIDER,
                "status": "ERROR",
                "error_type": "invalid_response",
            },
            "latency_ms": provider_latency_ms,
        })
        log_event(
            logger,
            logging.ERROR,
            "provider.complete",
            provider=LLM_PROVIDER,
            provider_status="error",
            error_type="invalid_response",
            latency_ms=round(provider_latency_ms, 3),
            exc_info=(
                type(exc),
                exc,
                exc.__traceback__,
            ),
        )
        total_latency_ms = (
            time.perf_counter() - request_started
        ) * 1000
        save_request_audit(
            db,
            request_id=request_id,
            risk_score=assessment.risk_score,
            action="ERROR",
            latency_ms=total_latency_ms,
            detector_results=detector_results,
        )
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="LLM provider returned an invalid response",
        ) from exc
    except Exception as exc:
        if provider_deadline.expired() or asyncio.get_running_loop().time() >= provider_deadline.when():
            error_type = "deadline_exceeded" if provider_called else "admission_deadline_exceeded"
        elif isinstance(exc, ProviderOverloadedError):
            error_type = "overloaded"
        elif isinstance(exc, APITimeoutError):
            error_type = "provider_timeout"
        else:
            error_type = "request_failed"
        provider_latency_ms = (
            time.perf_counter() - provider_started
        ) * 1000
        detector_results.append({
            "detector_name": "provider",
            "score": 1.0,
            "evidence": {
                "provider": LLM_PROVIDER,
                "status": "ERROR",
                "error_type": error_type,
            },
            "latency_ms": provider_latency_ms,
        })
        log_event(
            logger,
            logging.ERROR,
            "provider.complete",
            provider=LLM_PROVIDER,
            provider_status="error",
            error_type=error_type,
            latency_ms=round(provider_latency_ms, 3),
            exc_info=(
                type(exc),
                exc,
                exc.__traceback__,
            ),
        )
        total_latency_ms = (
            time.perf_counter() - request_started
        ) * 1000
        save_request_audit(
            db,
            request_id=request_id,
            risk_score=assessment.risk_score,
            action="ERROR",
            latency_ms=total_latency_ms,
            detector_results=detector_results,
        )
        raise HTTPException(
            status_code=(status.HTTP_503_SERVICE_UNAVAILABLE if error_type == "overloaded"
                         else status.HTTP_502_BAD_GATEWAY),
            detail="LLM provider busy" if error_type == "overloaded" else "LLM provider request failed",
        ) from exc

    provider_latency_ms = (
        time.perf_counter() - provider_started
    ) * 1000
    detector_results.append({
        "detector_name": "provider",
        "score": 0.0,
        "evidence": {
            "provider": LLM_PROVIDER,
            "status": "SUCCESS",
        },
        "latency_ms": provider_latency_ms,
    })
    log_event(
        logger,
        logging.INFO,
        "provider.complete",
        provider=LLM_PROVIDER,
        provider_status="success",
        latency_ms=round(provider_latency_ms, 3),
    )

    output_guard_started = time.perf_counter()
    output_result = data_guard.analyze(model_response)
    output_guard_latency_ms = (
        time.perf_counter() - output_guard_started
    ) * 1000

    # Audit stores only metadata about findings. Sensitive values and raw model
    # output are intentionally excluded.
    detector_results.append(
        {
            "detector_name": "data_guard",
            "score": 1.0 if output_result.findings else 0.0,
            "evidence": {
                "action": output_result.action.value,
                "finding_types": list(output_result.findings),
                "redaction_count": output_result.redaction_count,
            },
            "latency_ms": output_guard_latency_ms,
        }
    )
    log_event(
        logger,
        logging.INFO,
        "data_guard.complete",
        output_action=output_result.action.value,
        redaction_count=output_result.redaction_count,
        latency_ms=round(output_guard_latency_ms, 3),
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
    log_event(
        logger,
        logging.INFO,
        "gateway.decision",
        action=decision.action.value,
        risk_score=round(assessment.risk_score, 4),
        semantic_score=round(semantic_result.score, 4),
        duration_ms=round(total_latency_ms, 3),
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
        output_redaction_count=output_result.redaction_count,
        response=output_result.text,
    )
