# Async provider deadline

Current admission/queue implementation and latest validation: [Provider admission](PROVIDER_ADMISSION.md). Queue waiting now shares the provider total deadline.

Current runtime: async gateway → await GroqProvider.generate → AsyncGroq → HTTPX AsyncClient. Groq 1.7.0 already supports this interface; no dependency was added. Provider generate/close are async, and the provider call and shutdown no longer use a threadpool. Sync compatibility was unnecessary: Groq is the only implemented provider. Existing test assertions were retained while mocks/call sites were migrated to await/AsyncMock.

## Configuration and error contract

- GROQ_TIMEOUT_SECONDS=20: socket read/write/pool phase limit; connect min(5, configured timeout).
- GROQ_TOTAL_DEADLINE_SECONDS=20: separate finite positive gateway provider-operation budget.
- GROQ_MAX_RETRIES=0: one default SDK attempt; manual override 1/2 allows up to 2/3 attempts, only while budget remains.

The gateway wraps the whole awaited generate operation in asyncio.timeout. Client setup, network/pool waits, retries and backoff share this budget. There is no separately spawned provider task or shielded background generation. Cancellation is not caught by the SDK's Exception retry handlers because CancelledError is a BaseException. HTTPX closes a response on body-read cancellation. Local SDK source and official async API documentation were inspected: https://github.com/groq/groq-python#async-usage.

Deadline expiration retains the external provider-failure contract: generic 502, detail 'LLM provider request failed', audit ERROR, provider metadata error_type=deadline_exceeded, no DataGuard. Phase timeout is SDK APITimeoutError; admission hardening now records provider_timeout separately. External task cancellation propagates; it is not converted into a provider retry or swallowed. ALLOW/BLOCK/invalid-response behavior and privacy remain unchanged.

This is a cooperative async provider-operation deadline, not an entire HTTP-request deadline or a hard real-time bound. Guard execution and audit/DataGuard time are outside the provider budget. Blocking event-loop work can delay cancellation; cleanup takes time. Local cancellation closes local HTTP I/O; it cannot guarantee that a remote Groq generation or billing stops. DNS resolver worker activity and remote computation were not measured. Never interpret local cancellation as provider exactly-once or refunded generation.

## Client lifetime

One lazy AsyncGroq client is reused per provider on the application event loop. Initialization contains no await, so concurrent tasks cannot interleave construction; a threading lock is no longer needed. Awaited close detaches and closes the client once during application shutdown after requests drain. Do not share a live provider across concurrently running applications/event loops. Cancellation of one request does not close the shared client or cancel peers.

## Verification

The counts below are historical results from the async migration, before the
benign-intent fix. They are not the current release gate. The final product gate
is `python -m pytest -m "not research" -q`: 345 passed, zero failed.

All tests are offline; no slow/fault requests were sent to Groq.

- New async/deadline suite: 30 passed. Normal/before-deadline completion, cancellation before headers and during body read, no background tasks, stream cleanup, post-cancellation reuse, shutdown, and peer isolation verified.
- Retry/deadline matrix: timeout/429/500, retries 1/2, cancellation during backoff or attempt two; no later retry starts. Separate cases cancel the real SDK backoff sleep.
- 25 concurrent normal requests: 25 answers, one client, no leaked tasks, streams closed.
- 25 concurrent deadline requests: 25 generic failures, 25 cancelled body readers, one client, zero remaining active operations/tasks, streams closed. Test budget is 1 second to let all requests reach I/O; runtime remains 20 seconds.
- Real local TCP HTTP server with stalled body: actual HTTPX/httpcore connection closed on deadline; server observed EOF, server handler completed, client closed. This goes beyond cancellation of a mock coroutine.
- Focused async/provider/timeout/retry/validation/telemetry/DataGuard tests: 122 passed; timeout/retry suite retains 28 passing tests.
- Full pytest: 241 passed, 11 failed. Original 128 tests passed. The 11 failures are the unchanged SAFE false positives.
- SAFE regression independently: 17 passed, 11 failed / 28, with no xfail/skip or threshold adjustment.
- Existing invalid response evaluator: 16/16 passed after async migration. Synthetic latency evaluator: 24/24 passed. Simulated HTTP security evaluator: 24/27 passed; the three failures are existing SAFE false positives, all six attacks blocked with zero upstream calls.

Commands: `.tools/python311/python.exe -m pytest tests/test_provider_async_deadline.py -q`; `.tools/python311/python.exe -m pytest tests/test_provider_async_deadline.py tests/test_provider_timeouts.py tests/test_groq_provider.py tests/test_provider_factory.py tests/test_provider_response_validation.py tests/test_gateway_provider_telemetry.py tests/test_data_guard.py -q --tb=short`; `.tools/python311/python.exe -m pytest -q --tb=short --junitxml=reports/provider_async_deadline_pytest.xml`; `.tools/python311/python.exe -m pytest tests/test_safe_input_regression.py -q --tb=no`.

Stable v2 artifact SHA256 remains 9b1ab5ef1780b8a152f1ddb634f35cb3d617f70c1ad379c08bcd2ec09e9eadb5; semantic threshold remains 0.51. No V3 runtime or Laya decision changes, no training, commit or push.

Admission and queue bounds are now implemented; see PROVIDER_ADMISSION.md for the latest validation and next step.
