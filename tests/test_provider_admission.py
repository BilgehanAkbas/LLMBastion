import asyncio
import json
from unittest.mock import Mock

import httpx
import pytest
from fastapi import HTTPException

from app.providers.admission import ProviderAdmission
from app.providers.errors import ProviderOverloadedError
from app.routers import gateway
from scripts.provider_admission_eval import ControlledTransport, evaluate, wait_until
from test_provider_async_deadline import install_provider
from test_provider_response_validation import structured_logs
from test_provider_timeouts import CANARY, config_values


def test_admission_config_defaults_and_overrides(monkeypatch):
    for key in ("GROQ_MAX_CONCURRENT_REQUESTS", "GROQ_MAX_QUEUED_REQUESTS"):
        monkeypatch.delenv(key, raising=False)
    values = config_values(monkeypatch)
    assert values["GROQ_MAX_CONCURRENT_REQUESTS"] == 4
    assert values["GROQ_MAX_QUEUED_REQUESTS"] == 16
    monkeypatch.setenv("GROQ_MAX_CONCURRENT_REQUESTS", "2")
    monkeypatch.setenv("GROQ_MAX_QUEUED_REQUESTS", "0")
    values = config_values(monkeypatch)
    assert values["GROQ_MAX_CONCURRENT_REQUESTS"] == 2
    assert values["GROQ_MAX_QUEUED_REQUESTS"] == 0


@pytest.mark.parametrize("key,value", [
    ("GROQ_MAX_CONCURRENT_REQUESTS", "0"), ("GROQ_MAX_CONCURRENT_REQUESTS", "-1"),
    ("GROQ_MAX_CONCURRENT_REQUESTS", "1.5"), ("GROQ_MAX_CONCURRENT_REQUESTS", "bad"),
    ("GROQ_MAX_QUEUED_REQUESTS", "-1"), ("GROQ_MAX_QUEUED_REQUESTS", "1.5"),
    ("GROQ_MAX_QUEUED_REQUESTS", "bad"),
])
def test_invalid_admission_config_rejected(monkeypatch, key, value):
    monkeypatch.setenv(key, value)
    with pytest.raises(ValueError):
        config_values(monkeypatch)


@pytest.mark.parametrize("limit,queue", [(0, 1), (1, -1), (True, 1), (1, True), (1.5, 2), (2, 1.5)])
def test_invalid_admission_constructor_rejected(limit, queue):
    with pytest.raises(ValueError):
        ProviderAdmission(limit, queue)


@pytest.mark.asyncio
async def test_zero_queue_rejects_immediately_and_slot_reused():
    admission = ProviderAdmission(1, 0)
    async with admission.slot():
        with pytest.raises(ProviderOverloadedError):
            async with admission.slot():
                pytest.fail("Busy provider must not admit another request")
        assert admission.active == 1 and admission.queued == 0
    async with admission.slot():
        assert admission.active == 1
    assert admission.active == admission.queued == 0


@pytest.mark.asyncio
async def test_fifo_waiters_and_cancelled_waiter_do_not_consume_slot():
    admission = ProviderAdmission(1, 3)
    order = []

    async def waiter(name):
        async with admission.slot():
            order.append(name)

    async with admission.slot():
        first = asyncio.create_task(waiter("first"))
        await wait_until(lambda: admission.queued == 1)
        cancelled = asyncio.create_task(waiter("cancelled"))
        await wait_until(lambda: admission.queued == 2)
        last = asyncio.create_task(waiter("last"))
        await wait_until(lambda: admission.queued == 3)
        cancelled.cancel()
        with pytest.raises(asyncio.CancelledError):
            await cancelled
        assert admission.queued == 2 and admission.active == 1
    newcomer = asyncio.create_task(waiter("newcomer"))
    await asyncio.gather(first, last, newcomer)
    assert order == ["first", "last", "newcomer"]
    assert admission.active == admission.queued == 0


@pytest.mark.asyncio
async def test_cancel_during_slot_handoff_does_not_leak_permit():
    admission = ProviderAdmission(1, 1)
    entered = Mock()

    async def waiter():
        async with admission.slot():
            entered()

    holder = admission.slot()
    await holder.__aenter__()
    task = asyncio.create_task(waiter())
    await wait_until(lambda: admission.queued == 1)
    await holder.__aexit__(None, None, None)
    task.cancel()  # Permit assigned, but waiter has not resumed yet.
    with pytest.raises(asyncio.CancelledError):
        await task
    entered.assert_not_called()
    async with asyncio.timeout(1):
        async with admission.slot():
            assert admission.active == 1 and admission.queued == 0
    assert admission.active == 0


@pytest.mark.asyncio
async def test_exception_releases_slot():
    admission = ProviderAdmission(1, 1)
    with pytest.raises(RuntimeError):
        async with admission.slot():
            raise RuntimeError("Synthetic failure")
    async with admission.slot():
        assert admission.active == 1
    assert admission.active == admission.queued == 0


@pytest.mark.asyncio
async def test_total_budget_is_not_reset_after_queue_wait(monkeypatch):
    transport = ControlledTransport()
    provider, _, _, audits, output = install_provider(monkeypatch, transport)
    admission = ProviderAdmission(1, 1)
    monkeypatch.setattr(gateway, "provider_admission", admission)
    monkeypatch.setattr(gateway, "GROQ_TOTAL_DEADLINE_SECONDS", 0.3)
    # Isolate queue budget from the SDK's one-time platform metadata setup.
    transport.release.set()
    await provider.generate("warm")
    transport.release.clear()
    transport.started.clear()
    holder = admission.slot()
    await holder.__aenter__()
    holder_released = False
    loop = asyncio.get_running_loop()
    started = loop.time()
    task = asyncio.create_task(gateway.chat(gateway.ChatRequest(message="slow"), db=None))
    try:
        await wait_until(lambda: admission.queued == 1)
        await asyncio.sleep(0.2)
        await holder.__aexit__(None, None, None)
        holder_released = True
        await wait_until(lambda: transport.active == 1)
        with pytest.raises(HTTPException) as error:
            await task
        # A reset would allow another 0.3s after the 0.2s queue wait.
        assert loop.time() - started < 0.45
        assert error.value.status_code == 502 and transport.cancelled == 1
        assert audits[0]["detector_results"][-1]["evidence"]["error_type"] == "deadline_exceeded"
        assert admission.active == admission.queued == 0
        output.assert_not_called()
    finally:
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)
        if not holder_released:
            await holder.__aexit__(None, None, None)
        await provider.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("case,error_type", [("timeout", "provider_timeout"), ("failure", "request_failed")])
async def test_upstream_error_types_and_privacy(monkeypatch, structured_logs, case, error_type):
    transport = ControlledTransport()
    transport.release.set()
    provider, _, _, audits, output = install_provider(monkeypatch, transport)
    admission = ProviderAdmission(1, 1)
    monkeypatch.setattr(gateway, "provider_admission", admission)
    try:
        with pytest.raises(HTTPException) as error:
            await gateway.chat(gateway.ChatRequest(message=case), db=None)
        assert error.value.status_code == 502 and error.value.detail == "LLM provider request failed"
        assert audits[0]["action"] == "ERROR"
        assert audits[0]["detector_results"][-1]["evidence"]["error_type"] == error_type
        output.assert_not_called()
        assert admission.active == admission.queued == 0
        assert CANARY not in json.dumps(audits) + structured_logs.getvalue() + error.value.detail
    finally:
        await provider.close()


@pytest.mark.asyncio
async def test_block_bypasses_full_admission(monkeypatch):
    admission = ProviderAdmission(1, 0)
    monkeypatch.setattr(gateway, "provider_admission", admission)
    provider_call = Mock(side_effect=AssertionError("Provider must not be called"))
    monkeypatch.setattr(gateway.provider, "generate", provider_call)
    from types import SimpleNamespace as NS
    monkeypatch.setattr(gateway.rule_guard, "analyze", lambda _: NS(score=1, matches=(), matched_rules=()))
    monkeypatch.setattr(gateway.semantic_guard, "analyze", lambda _: NS(score=0))
    monkeypatch.setattr(gateway, "save_request_audit", lambda *args, **fields: None)
    output = Mock()
    monkeypatch.setattr(gateway.data_guard, "analyze", output)
    async with admission.slot():
        result = await gateway.chat(gateway.ChatRequest(message="Synthetic blocked case"), db=None)
        assert result.action.value == "BLOCK" and result.response is None
        assert admission.active == 1 and admission.queued == 0
    provider_call.assert_not_called()
    output.assert_not_called()


@pytest.mark.asyncio
@pytest.mark.parametrize("environment,message", [("development", "LLM provider busy"),
                                                 ("production", "Service temporarily unavailable")])
async def test_overload_http_contract(monkeypatch, structured_logs, environment, message):
    from app.main import create_app

    transport = ControlledTransport()
    provider, _, _, audits, output = install_provider(monkeypatch, transport)
    admission = ProviderAdmission(1, 0)
    monkeypatch.setattr(gateway, "provider_admission", admission)
    app = create_app(app_env=environment)
    try:
        async with admission.slot():
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://synthetic") as client:
                response = await client.post("/api/v1/chat", json={"message": "Synthetic overload"})
        assert response.status_code == 503
        assert response.json() == {"detail": message, "error": {"code": "service_unavailable", "message": message}}
        assert response.headers["X-Request-ID"]
        assert audits[0]["action"] == "ERROR"
        assert audits[0]["detector_results"][-1]["evidence"]["error_type"] == "overloaded"
        assert transport.started == [] and admission.active == admission.queued == 0
        output.assert_not_called()
        assert CANARY not in response.text + json.dumps(audits) + structured_logs.getvalue()
    finally:
        await provider.close()


@pytest.mark.asyncio
async def test_offline_load_scenarios():
    report = await evaluate()
    rows = {r["scenario"]: r for r in report["scenarios"]}
    assert report["groq_network_calls"] == 0
    assert rows["below_limit"]["max_observed_upstream_concurrency"] == 3
    assert rows["above_limit"]["max_observed_upstream_concurrency"] == 4
    assert rows["above_limit"]["peak_queued_requests"] == 16
    assert rows["queue_full"]["rejected_count"] == 3
    assert rows["queued_deadline"]["deadline_before_provider_count"] == 2
    assert rows["queued_deadline"]["upstream_attempts"] == 1
    assert rows["provider_timeout"]["provider_timeout_count"] == 1
    assert rows["mixed"]["cancelled_requests"] == 2 and rows["mixed"]["upstream_attempts"] == 5
    assert all(r["leaked_tasks"] == r["leaked_slots"] == r["remaining_queued"] == 0 for r in rows.values())
    assert all(r["client_closed"] and r["privacy_check"] for r in rows.values())
