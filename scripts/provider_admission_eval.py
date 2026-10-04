"""Offline load of the gateway/provider path with real AsyncGroq + mock HTTP.

Guards and audit persistence are isolated; policy, admission, deadline, SDK,
error contract and DataGuard run normally. No Groq network requests are made.
"""
import asyncio
from contextlib import AsyncExitStack
import io
import json
import logging
from pathlib import Path
import sys
import time
from types import SimpleNamespace as NS
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import groq
import httpx
from fastapi import HTTPException

from app.providers.admission import ProviderAdmission
from app.core.observability import StructuredJsonFormatter
from app.providers.groq_provider import GroqProvider
from app.routers import gateway

CANARY = "synthetic-upstream-private-detail"


class ControlledTransport(httpx.AsyncBaseTransport):
    def __init__(self):
        self.release = asyncio.Event()
        self.started = []
        self.active = self.peak = self.cancelled = self.closed = 0

    async def handle_async_request(self, request):
        case = json.loads(request.content)["messages"][-1]["content"]
        self.started.append(case)
        self.active += 1
        self.peak = max(self.peak, self.active)
        try:
            await self.release.wait()
            if case == "timeout":
                raise httpx.ReadTimeout(CANARY, request=request)
            if case == "failure":
                return httpx.Response(500, json={"error": {"message": CANARY}})
            return httpx.Response(200, json={
                "id": "synthetic", "object": "chat.completion", "created": 0, "model": "synthetic-model",
                "choices": [{"index": 0, "message": {"role": "assistant", "content": "Synthetic answer"}, "finish_reason": "stop"}],
            })
        except asyncio.CancelledError:
            self.cancelled += 1
            raise
        finally:
            self.active -= 1

    async def aclose(self):
        self.closed += 1


async def wait_until(predicate):
    async with asyncio.timeout(3):
        while not predicate():
            await asyncio.sleep(0.001)


async def scenario(name, limit, queue_limit):
    admission = ProviderAdmission(limit, queue_limit)
    transport = ControlledTransport()
    client = httpx.AsyncClient(transport=transport)
    sdk = groq.AsyncGroq(api_key="synthetic-key", http_client=client, max_retries=0)
    provider = GroqProvider(api_key="synthetic-key", model="synthetic-model")
    provider._client = sdk
    audits, tasks, latencies = [], [], []
    before = asyncio.all_tasks()
    queued_peak = 0
    logs = io.StringIO()
    handler = logging.StreamHandler(logs)
    handler.setFormatter(StructuredJsonFormatter())
    logger = logging.getLogger("app")
    logger.addHandler(handler)

    async def call(case):
        started = time.perf_counter()
        try:
            return await gateway.chat(gateway.ChatRequest(message=case), db=None)
        finally:
            latencies.append((time.perf_counter() - started) * 1000)

    def launch(case):
        task = asyncio.create_task(call(case))
        tasks.append(task)
        return task

    output = Mock(wraps=gateway.data_guard.analyze)
    with patch.object(gateway, "provider", provider), patch.object(gateway, "provider_admission", admission), \
            patch.object(gateway, "GROQ_TOTAL_DEADLINE_SECONDS", 3), \
            patch.object(gateway.rule_guard, "analyze", return_value=NS(score=0, matches=(), matched_rules=())), \
            patch.object(gateway.semantic_guard, "analyze", return_value=NS(score=0)), \
            patch.object(gateway, "save_request_audit", side_effect=lambda db, **fields: audits.append(fields)), \
            patch.object(gateway.data_guard, "analyze", output):
        try:
            if name == "below_limit":
                for i in range(limit - 1):
                    launch(f"normal{i}")
                await wait_until(lambda: transport.active == limit - 1)
            elif name in {"above_limit", "queue_full"}:
                for i in range(limit):
                    launch(f"active{i}")
                await wait_until(lambda: transport.active == limit)
                for i in range(queue_limit):
                    launch(f"queued{i}")
                await wait_until(lambda: admission.queued == queue_limit)
                queued_peak = admission.queued
                if name == "queue_full":
                    rejected = [launch(f"overflow{i}") for i in range(3)]
                    results = await asyncio.gather(*rejected, return_exceptions=True)
                    assert all(isinstance(r, HTTPException) and r.status_code == 503 for r in results)
                    assert transport.active == limit and len(transport.started) == limit
            elif name == "queued_deadline":
                # Independent occupied slot keeps waiting requests queued
                # beyond their budget; it has no competing gateway deadline.
                async def holder():
                    async with admission.slot():
                        return await provider.generate("holder")
                holding = asyncio.create_task(holder())
                tasks.append(holding)
                await wait_until(lambda: transport.active == 1)
                with patch.object(gateway, "GROQ_TOTAL_DEADLINE_SECONDS", 0.1):
                    waiting = [launch(f"expired{i}") for i in range(queue_limit)]
                    await wait_until(lambda: admission.queued == queue_limit)
                    queued_peak = admission.queued
                    results = await asyncio.gather(*waiting, return_exceptions=True)
                assert all(isinstance(r, HTTPException) and r.status_code == 502 for r in results)
                assert transport.started == ["holder"] and admission.queued == 0
            elif name == "provider_timeout":
                launch("timeout")
                await wait_until(lambda: transport.active == 1)
                for i in range(queue_limit):
                    launch(f"normal{i}")
                await wait_until(lambda: admission.queued == queue_limit)
                queued_peak = admission.queued
            elif name == "mixed":
                active_cancel = launch("active_cancel")
                launch("timeout")
                await wait_until(lambda: transport.active == 2)
                launch("slow")
                launch("normal1")
                queued_cancel = launch("queued_cancel")
                launch("normal2")
                await wait_until(lambda: admission.queued == 4)
                queued_peak = admission.queued
                queued_cancel.cancel()
                await asyncio.gather(queued_cancel, return_exceptions=True)
                active_cancel.cancel()
                await asyncio.gather(active_cancel, return_exceptions=True)
                await wait_until(lambda: "slow" in transport.started)
                assert "queued_cancel" not in transport.started
            else:
                raise ValueError("Unknown synthetic scenario")
            transport.release.set()
            results = await asyncio.gather(*tasks, return_exceptions=True)
            assert admission.active == admission.queued == transport.active == 0
            # Prove every slot is reusable, rather than just trusting counters.
            async with asyncio.timeout(1):
                async with AsyncExitStack() as stack:
                    for _ in range(limit):
                        await stack.enter_async_context(admission.slot())
                    assert admission.active == limit
            await asyncio.sleep(0)
            leaked_tasks = len(asyncio.all_tasks() - before)
            errors = [d["evidence"]["error_type"] for a in audits for d in a["detector_results"]
                      if d["detector_name"] == "provider" and d["evidence"]["status"] == "ERROR"]
            row = {
                "scenario": name, "max_concurrent": limit, "max_queue": queue_limit,
                "request_count": len(tasks), "max_observed_upstream_concurrency": transport.peak,
                "peak_queued_requests": queued_peak, "upstream_attempts": len(transport.started),
                "rejected_count": errors.count("overloaded"),
                "deadline_before_provider_count": errors.count("admission_deadline_exceeded"),
                "provider_timeout_count": errors.count("provider_timeout"),
                "cancelled_requests": sum(isinstance(r, asyncio.CancelledError) for r in results),
                "allowed_requests": sum(getattr(getattr(r, "action", None), "value", None) == "ALLOW" for r in results),
                "error_responses": sum(isinstance(r, HTTPException) for r in results),
                "cancelled_upstream_operations": transport.cancelled,
                "data_guard_calls": output.call_count,
                "leaked_tasks": leaked_tasks, "leaked_slots": admission.active,
                "remaining_queued": admission.queued,
                "mean_gateway_latency_ms": round(sum(latencies) / len(latencies), 3),
                "privacy_check": CANARY not in (json.dumps(audits) + logs.getvalue()
                                  + "".join(str(r.detail) for r in results if isinstance(r, HTTPException))),
            }
            assert transport.peak <= limit and leaked_tasks == 0 and row["privacy_check"]
        finally:
            for task in tasks:
                if not task.done():
                    task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)
            await provider.close()
            logger.removeHandler(handler)
    row["client_closed"] = client.is_closed and transport.closed == 1
    return row


async def evaluate():
    profiles = [("below_limit", 4, 16), ("above_limit", 4, 16), ("queue_full", 2, 3),
                ("queued_deadline", 1, 2), ("provider_timeout", 1, 2), ("mixed", 2, 8)]
    rows = [await scenario(*profile) for profile in profiles]
    # Every reported success is checked, not inferred from transport counts.
    expected = [(3, 0, 0), (20, 0, 0), (5, 3, 0), (0, 2, 0), (2, 1, 0), (3, 1, 2)]
    for row, (allowed, errors, cancelled) in zip(rows, expected):
        row["passed"] = (row["allowed_requests"] == allowed and row["error_responses"] == errors
                         and row["cancelled_requests"] == cancelled and row["client_closed"]
                         and row["leaked_tasks"] == row["leaked_slots"] == row["remaining_queued"] == 0
                         and row["max_observed_upstream_concurrency"] <= row["max_concurrent"]
                         and row["peak_queued_requests"] <= row["max_queue"] and row["privacy_check"])
        assert row["passed"], f"Synthetic scenario failed: {row['scenario']}"
    return {"synthetic_only": True, "groq_network_calls": 0,
            "guards_and_audit_persistence_isolated": True,
            "runtime_defaults": {"max_concurrent": 4, "max_queued": 16},
            "passed": sum(r["passed"] for r in rows), "total": len(rows), "scenarios": rows}


if __name__ == "__main__":
    from app.core.observability import configure_logging
    configure_logging("WARNING")
    report = asyncio.run(evaluate())
    destination = ROOT / "reports/provider_admission_load.json"
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2))
