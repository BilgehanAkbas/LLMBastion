from __future__ import annotations

import time
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session
from starlette import status

from ..core.config import GROQ_MODEL
from ..core.observability import get_request_id
from ..policies.input_policy import PolicyAction
from .gateway import (
    ChatRequest,
    ChatResponse,
    chat as gateway_chat,
    get_db,
    input_policy,
    risk_engine,
    rule_guard,
    semantic_guard,
)

router = APIRouter(prefix="/v1", tags=["Public API"])
db_dependency = Annotated[Session, Depends(get_db)]


class GuardRequest(BaseModel):
    input: str = Field(min_length=1, max_length=4000)


class GuardResponse(BaseModel):
    request_id: str
    action: PolicyAction
    risk_score: float
    semantic_score: float
    matched_rules: tuple[str, ...]
    triggered_detectors: tuple[str, ...]
    provider_called: bool = False


@router.post("/guard", response_model=GuardResponse)
async def guard(request: GuardRequest):
    rule_result = rule_guard.analyze(request.input)
    try:
        semantic_result = semantic_guard.analyze(request.input)
    except RuntimeError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=str(exc),
        ) from exc

    assessment = risk_engine.assess(
        rule_score=rule_result.score,
        semantic_score=semantic_result.score,
    )
    decision = input_policy.decide_assessment(assessment)

    return GuardResponse(
        request_id=get_request_id() or "standalone-guard",
        action=decision.action,
        risk_score=assessment.risk_score,
        semantic_score=semantic_result.score,
        matched_rules=rule_result.matched_rules,
        triggered_detectors=assessment.triggered_detectors,
        provider_called=False,
    )


class CompletionMessage(BaseModel):
    role: Literal["user"]
    content: str = Field(min_length=1, max_length=4000)


class ChatCompletionRequest(BaseModel):
    model: str | None = Field(
        default=None,
        min_length=1,
        max_length=200,
    )
    messages: list[CompletionMessage] = Field(min_length=1, max_length=1)
    stream: bool = False


class AssistantMessage(BaseModel):
    role: Literal["assistant"] = "assistant"
    content: str | None


class CompletionChoice(BaseModel):
    index: int = 0
    message: AssistantMessage
    finish_reason: Literal["stop", "content_filter"]


class LLMBastionMetadata(BaseModel):
    request_id: str
    action: PolicyAction
    risk_score: float
    semantic_score: float
    output_action: str | None = None
    output_findings: tuple[str, ...] = ()
    output_redaction_count: int = 0


class ChatCompletionResponse(BaseModel):
    id: str
    object: Literal["chat.completion"] = "chat.completion"
    created: int
    model: str
    choices: list[CompletionChoice]
    llmbastion: LLMBastionMetadata


@router.post("/chat/completions", response_model=ChatCompletionResponse)
async def chat_completions(
    request: ChatCompletionRequest,
    db: db_dependency,
):
    if request.stream:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Streaming is not supported yet",
        )

    if request.model is not None and request.model != GROQ_MODEL:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                "Requested model does not match the configured "
                "LLMBastion provider model"
            ),
        )

    gateway_result: ChatResponse = await gateway_chat(
        ChatRequest(message=request.messages[0].content),
        db,
    )
    blocked = gateway_result.action == PolicyAction.BLOCK

    return ChatCompletionResponse(
        id="chatcmpl-" + gateway_result.request_id.replace("-", ""),
        created=int(time.time()),
        model=GROQ_MODEL,
        choices=[
            CompletionChoice(
                message=AssistantMessage(
                    content=None if blocked else gateway_result.response
                ),
                finish_reason="content_filter" if blocked else "stop",
            )
        ],
        llmbastion=LLMBastionMetadata(
            request_id=gateway_result.request_id,
            action=gateway_result.action,
            risk_score=gateway_result.risk_score,
            semantic_score=gateway_result.semantic_score,
            output_action=(
                gateway_result.output_action.value
                if gateway_result.output_action is not None
                else None
            ),
            output_findings=gateway_result.output_findings,
            output_redaction_count=gateway_result.output_redaction_count,
        ),
    )
