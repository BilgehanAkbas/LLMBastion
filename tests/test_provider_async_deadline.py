"""Cancellation checks use real AsyncGroq/HTTPX, never the Groq service."""
import asyncio
import json
import time
from types import SimpleNamespace as NS
from unittest.mock import AsyncMock, Mock

import groq
import httpx
import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

from app.providers.groq_provider import GroqProvider
from app.providers.admission import ProviderAdmission
from app.routers import gateway
from test_provider_timeouts import CANARY, config_values

ANSWER = json.dumps({
    "id": "synthetic", "object": "chat.completion", "created": 0, "model": "synthetic-model",
    "choices": [{"index": 0, "message": {"role": "assistant", "content": "Synthetic answer"}, "finish_reason": "stop"}],
}).encode()


class DelayedStream(httpx.AsyncByteStream):
    def __init__(self, owner, delay):
        self.owner = owner
        self.delay = delay
        self.closed = False
        owner.streams.append(self)

    async def __aiter__(self):
        self.owner.active += 1
        try:
            yield ANSWER[:10]
            await asyncio.sleep(self.delay)
            yield ANSWER[10:]
            self.owner.completed += 1
        except asyncio.CancelledError:
            self.owner.cancelled += 1
            raise
        finally:
            self.owner.active -= 1

    async def aclose(self):
        self.closed = True


class SyntheticTransport(httpx.AsyncBaseTransport):
    def __init__(self, delay=0.002, *, headers_delay=False, status=200):
        self.delay = delay
        self.headers_delay = headers_delay
        self.status = status
        self.attempts = self.active = self.cancelled = self.completed = self.closed = 0
        self.streams = []

    async def handle_async_request(self, request):
        self.attempts += 1
        if self.status == "timeout":
            raise httpx.ReadTimeout(CANARY, request=request)
        if self.status != 200:
            return httpx.Response(self.status, json={"error": {"message": CANARY}})
        if self.headers_delay:
            self.active += 1
            try:
                await asyncio.sleep(self.delay)
            except asyncio.CancelledError:
                self.cancelled += 1
                raise
            finally:
                self.active -= 1
        return httpx.Response(200, stream=DelayedStream(self, 0 if self.headers_delay else self.delay))

    async def aclose(self):
        self.closed += 1


def install_provider(monkeypatch, transport, retries=0):
    # These earlier tests isolate I/O cancellation with all 25 calls admitted.
    # Bounded admission and queued cancellation have their own load suite.
    monkeypatch.setattr(gateway, "provider_admission", ProviderAdmission(25, 25))
    real = groq.AsyncGroq
    clients = []

    def construct(**kwargs):
        client = httpx.AsyncClient(transport=transport)
        clients.append(client)
        return real(**kwargs, http_client=client)

    constructor = Mock(side_effect=construct)
    monkeypatch.setattr(groq, "AsyncGroq", constructor)
    provider = GroqProvider(api_key="synthetic-key", model="synthetic-model", max_retries=retries)
    monkeypatch.setattr(gateway, "provider", provider)
    monkeypatch.setattr(gateway.rule_guard, "analyze", lambda _: NS(score=0, matches=(), matched_rules=()))
    monkeypatch.setattr(gateway.semantic_guard, "analyze", lambda _: NS(score=0))
    audits = []
    monkeypatch.setattr(gateway, "save_request_audit", lambda db, **fields: audits.append(fields))
    output = Mock(wraps=gateway.data_guard.analyze)
    monkeypatch.setattr(gateway.data_guard, "analyze", output)
    return provider, constructor, clients, audits, output


async def call_gateway():
    return await gateway.chat(gateway.ChatRequest(message="Synthetic question"), db=None)


def test_deadline_default_and_override(monkeypatch):
    monkeypatch.delenv("GROQ_TOTAL_DEADLINE_SECONDS", raising=False)
    assert config_values(monkeypatch)["GROQ_TOTAL_DEADLINE_SECONDS"] == 20
    monkeypatch.setenv("GROQ_TOTAL_DEADLINE_SECONDS", "0.125")
    assert config_values(monkeypatch)["GROQ_TOTAL_DEADLINE_SECONDS"] == 0.125


@pytest.mark.parametrize("value", ["0", "-1", "nan", "inf", "-inf", "bad"])
def test_invalid_deadline_rejected(monkeypatch, value):
    monkeypatch.setenv("GROQ_TOTAL_DEADLINE_SECONDS", value)
    with pytest.raises(ValueError):
        config_values(monkeypatch)


@pytest.mark.asyncio
@pytest.mark.parametrize("delay", [0, 0.01])
async def test_response_before_deadline(monkeypatch, delay):
    transport = SyntheticTransport(delay)
    provider, _, clients, audits, output = install_provider(monkeypatch, transport)
    monkeypatch.setattr(gateway, "GROQ_TOTAL_DEADLINE_SECONDS", 0.5)
    try:
        response = await call_gateway()
        assert response.action.value == "ALLOW" and response.response == "Synthetic answer"
        assert transport.attempts == 1 and transport.cancelled == 0
        assert audits[0]["action"] == "ALLOW" and output.call_count == 1
        assert all(stream.closed for stream in transport.streams)
    finally:
        await provider.close()
    assert clients[0].is_closed and transport.closed == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("headers_delay", [False, True])
async def test_deadline_cancels_io_without_background_work(monkeypatch, headers_delay, caplog):
    transport = SyntheticTransport(10, headers_delay=headers_delay)
    provider, _, clients, audits, output = install_provider(monkeypatch, transport)
    # Isolate cancellation of active I/O from variable cold SDK setup time.
    provider._get_client()
    monkeypatch.setattr(gateway, "GROQ_TOTAL_DEADLINE_SECONDS", 0.03)
    before = asyncio.all_tasks()
    started = time.perf_counter()
    try:
        with pytest.raises(HTTPException) as error:
            await call_gateway()
        elapsed = time.perf_counter() - started
        assert error.value.status_code == 502
        assert error.value.detail == "LLM provider request failed"
        assert elapsed < 1
        assert transport.cancelled == 1 and transport.active == transport.completed == 0
        assert all(stream.closed for stream in transport.streams)
        assert audits[0]["action"] == "ERROR"
        assert audits[0]["detector_results"][-1]["evidence"]["error_type"] == "deadline_exceeded"
        output.assert_not_called()
        assert CANARY not in json.dumps(audits) + error.value.detail + caplog.text
        await asyncio.sleep(0.02)
        assert transport.attempts == 1 and transport.completed == 0
        assert not (asyncio.all_tasks() - before)
        # Cancellation only terminates this request, not the reusable client.
        transport.delay = 0
        assert (await call_gateway()).response == "Synthetic answer"
    finally:
        await provider.close()
    assert clients[0].is_closed and transport.closed == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("retries", [1, 2])
@pytest.mark.parametrize("stage", ["backoff", "second_attempt"])
@pytest.mark.parametrize("status", [429, 500, "timeout"])
async def test_deadline_covers_retry_chain(monkeypatch, retries, stage, status):
    transport = SyntheticTransport(status=status)
    provider, _, _, audits, output = install_provider(monkeypatch, transport, retries)
    backoff_started = asyncio.Event()

    async def backoff(*args, **kwargs):
        backoff_started.set()
        if stage == "second_attempt":
            transport.status = 200
            transport.delay = 10
            await asyncio.sleep(0.001)
        else:
            await asyncio.sleep(10)

    monkeypatch.setattr(groq._base_client.AsyncAPIClient, "_sleep_for_retry", backoff)
    monkeypatch.setattr(gateway, "GROQ_TOTAL_DEADLINE_SECONDS", 0.05)
    try:
        with pytest.raises(HTTPException) as error:
            await call_gateway()
        assert error.value.status_code == 502 and backoff_started.is_set()
        assert transport.attempts == (1 if stage == "backoff" else 2)
        assert transport.active == 0 and all(stream.closed for stream in transport.streams)
        await asyncio.sleep(0.02)
        assert transport.attempts == (1 if stage == "backoff" else 2)
        assert audits[0]["action"] == "ERROR"
        output.assert_not_called()
    finally:
        await provider.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [429, 500])
async def test_deadline_cancels_real_sdk_backoff(monkeypatch, status):
    transport = SyntheticTransport(status=status)
    provider, _, _, _, _ = install_provider(monkeypatch, transport, retries=2)
    monkeypatch.setattr(groq._base_client.AsyncAPIClient, "_calculate_retry_timeout", lambda *args: 10)
    monkeypatch.setattr(gateway, "GROQ_TOTAL_DEADLINE_SECONDS", 0.05)
    before = asyncio.all_tasks()
    try:
        with pytest.raises(HTTPException) as error:
            await call_gateway()
        assert error.value.status_code == 502 and transport.attempts == 1
        await asyncio.sleep(0.02)
        assert transport.attempts == 1 and not (asyncio.all_tasks() - before)
    finally:
        await provider.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("deadline_requests", [False, True])
async def test_25_concurrent_requests_no_leaks(monkeypatch, deadline_requests):
    transport = SyntheticTransport(10 if deadline_requests else 0.01)
    provider, constructor, clients, audits, output = install_provider(monkeypatch, transport)
    # Leave enough setup time for all 25 requests to reach the stalled body.
    monkeypatch.setattr(gateway, "GROQ_TOTAL_DEADLINE_SECONDS", 1 if deadline_requests else 2)
    before = asyncio.all_tasks()
    try:
        results = await asyncio.gather(*(call_gateway() for _ in range(25)), return_exceptions=True)
        if deadline_requests:
            assert all(isinstance(result, HTTPException) and result.status_code == 502 for result in results)
        else:
            assert all(result.response == "Synthetic answer" for result in results)
        assert constructor.call_count == 1 and transport.attempts == 25
        assert transport.active == 0 and transport.cancelled == (25 if deadline_requests else 0)
        assert len(audits) == 25
        assert {audit["action"] for audit in audits} == {"ERROR" if deadline_requests else "ALLOW"}
        assert output.call_count == (0 if deadline_requests else 25)
        assert all(stream.closed for stream in transport.streams)
        await asyncio.sleep(0)
        assert not (asyncio.all_tasks() - before)
    finally:
        await provider.close()
        await provider.close()
    assert clients[0].is_closed and transport.closed == 1


@pytest.mark.asyncio
async def test_cancelling_one_request_does_not_cancel_another(monkeypatch):
    transport = SyntheticTransport(0.03)
    provider, _, _, _, _ = install_provider(monkeypatch, transport)
    monkeypatch.setattr(gateway, "GROQ_TOTAL_DEADLINE_SECONDS", 2)
    first = asyncio.create_task(call_gateway())
    second = asyncio.create_task(call_gateway())
    try:
        async with asyncio.timeout(1):
            while transport.active < 2:
                await asyncio.sleep(0.001)
        first.cancel()
        with pytest.raises(asyncio.CancelledError):
            await first
        assert (await second).response == "Synthetic answer"
        assert transport.cancelled == 1 and transport.completed == 1 and transport.active == 0
        assert all(stream.closed for stream in transport.streams)
    finally:
        await asyncio.gather(first, second, return_exceptions=True)
        await provider.close()


def test_application_shutdown_closes_real_async_client(monkeypatch):
    import app.main as main

    transport = SyntheticTransport()
    provider, constructor, clients, _, _ = install_provider(monkeypatch, transport)
    monkeypatch.setattr(main, "gateway_provider", provider)
    with TestClient(main.create_app()) as client:
        assert client.post("/api/v1/chat", json={"message": "Synthetic question"}).status_code == 200
        assert not clients[0].is_closed
    assert clients[0].is_closed and transport.closed == 1 and constructor.call_count == 1


@pytest.mark.asyncio
async def test_real_local_http_connection_closed_on_deadline(monkeypatch):
    """Real HTTPX/httpcore socket: stalled body closes locally on cancellation."""
    disconnected = asyncio.Event()
    handlers = set()

    async def handle(reader, writer):
        handlers.add(asyncio.current_task())
        try:
            await reader.readuntil(b"\r\n\r\n")
            # Consume request body before observing client disconnect.
            # Reader can contain POST bytes; EOF, rather than one read, matters.
            writer.write(b"HTTP/1.1 200 OK\r\nContent-Type: application/json\r\nContent-Length: 9999\r\n\r\n{")
            await writer.drain()
            while await reader.read(4096):
                pass
            disconnected.set()
        finally:
            writer.close()
            await writer.wait_closed()
            handlers.discard(asyncio.current_task())

    server = await asyncio.start_server(handle, "127.0.0.1", 0)
    port = server.sockets[0].getsockname()[1]
    http_client = httpx.AsyncClient(trust_env=False)
    sdk = groq.AsyncGroq(api_key="synthetic-key", base_url=f"http://127.0.0.1:{port}", http_client=http_client, max_retries=0)
    provider = GroqProvider(api_key="synthetic-key", model="synthetic-model")
    provider._client = sdk
    # Guard/policy/audit fixtures, but use the actual socket client.
    install_provider(monkeypatch, SyntheticTransport())
    monkeypatch.setattr(gateway, "provider", provider)
    monkeypatch.setattr(gateway, "GROQ_TOTAL_DEADLINE_SECONDS", 0.2)
    try:
        with pytest.raises(HTTPException) as error:
            await call_gateway()
        assert error.value.status_code == 502
        await asyncio.wait_for(disconnected.wait(), 1)
        if handlers:
            await asyncio.gather(*handlers)
        assert not handlers
    finally:
        await provider.close()
        server.close()
        await server.wait_closed()
        for task in handlers:
            task.cancel()
        await asyncio.gather(*handlers, return_exceptions=True)
    assert http_client.is_closed
