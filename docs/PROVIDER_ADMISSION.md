# Provider admission and bounded queue

Runtime defaults: `GROQ_MAX_CONCURRENT_REQUESTS=4`, `GROQ_MAX_QUEUED_REQUESTS=16`. Positive concurrency and nonnegative queue limits are validated. Queue=0 rejects immediately whenever all active slots are occupied. Limits are per application process/event loop; N workers can have N times the configured capacity. No new dependency, queue framework, fallback or retry policy was added.

## Flow and ownership

Input guards → policy → BLOCK return, or total provider deadline → admission slot → AsyncGroq generation/retries → release slot → DataGuard → response.

`ProviderAdmission` uses asyncio.BoundedSemaphore and a waiter counter. Admission check/count update has no await gap. Semaphore locked state includes pending handoffs, so new arrivals do not overtake existing waiters. Queue count includes a woken waiter until it resumes, conservatively bounding pending work. A slot covers the entire provider operation including retries/backoff, and releases in finally after completion, exception or cancellation. A cancelled waiter removes its queue count; semaphore cancellation restores a permit even during handoff.

The limiter is recreated during application lifespan startup because asyncio waiters belong to that event loop. As with the existing pooled AsyncGroq client, concurrently running independent applications must not share the global runtime instance. BLOCK never enters admission. Direct provider.generate callers are outside gateway admission; the repository's runtime provider call site is the gateway route.

Queue wait is inside `GROQ_TOTAL_DEADLINE_SECONDS=20`, together with setup, HTTP waits and retries. The budget is never reset on slot acquisition. After a handoff the gateway checks the deadline again before dispatch, preventing a late timer callback from starting an expired request. This remains cooperative asyncio cancellation; input guard/DB work, output guard/audit time and remote provider computation are not bounded by this provider budget. Ingress connections, pre-policy work and multi-worker global capacity are outside this small admission layer.

## Error contract

| Condition | HTTP | Audit action | Provider error_type |
|---|---|---|---|
| Provider failure / upstream 429 or 500 | 502 | ERROR | request_failed |
| SDK phase timeout | 502 | ERROR | provider_timeout |
| Total deadline during generation/backoff | 502 | ERROR | deadline_exceeded |
| Total deadline while queued / before dispatch | 502 | ERROR | admission_deadline_exceeded |
| Queue full | 503 | ERROR | overloaded |

Generic 502 detail remains `LLM provider request failed`. Overload uses `LLM provider busy` and the existing structured `service_unavailable` response; production sanitizes its message to `Service temporarily unavailable`. Missing provider config and invalid completion retain their existing distinct paths. DataGuard only runs after a successful provider response. No raw prompts, responses, private error details or credentials were added to admission telemetry/audit. Failure privacy tests check structured logs, response and audit.

## Actual synthetic load results

Real AsyncGroq/HTTPX with controlled async transport; no Groq network calls. Guards and audit persistence are mocked to isolate this gateway/provider behavior; policy, admission, deadline, SDK, error paths and DataGuard run. HTTP response contract is separately tested through ASGI routing in development and production. These are deterministic correctness checks, not provider throughput benchmarks.

| Scenario | Active limit | Queue limit | Observed max upstream | Peak queued | Overload rejects | Deadline before provider |
|---|---:|---:|---:|---:|---:|---:|
| Below limit | 4 | 16 | 3 | 0 | 0 | 0 |
| Above limit | 4 | 16 | 4 | 16 | 0 | 0 |
| Queue full | 2 | 3 | 2 | 3 | 3 | 0 |
| Queued deadline | 1 | 2 | 1 | 2 | 0 | 2 |
| Provider timeout | 1 | 2 | 1 | 2 | 0 | 0 |
| Mixed | 2 | 8 | 2 | 4 | 0 | 0 |

All six scenarios passed explicit success/error/cancellation checks. The 20 above-limit requests all returned ALLOW. Queue-full overflow made zero provider calls. Queued-deadline uses one independently held slot; the two expired gateway requests made zero provider calls. Mixed load returned three successful answers, one provider timeout, and two cancellations; cancelled queue entry made no upstream attempt. Across all scenarios: zero leaked tasks/slots/waiters; all clients closed. Every slot was reacquired concurrently after each load case to verify permit reuse, rather than relying only on active counters. Output guards ran only for successful gateway responses.

Artifacts: `reports/provider_admission_load.json`, `reports/provider_admission_pytest.xml`.

## Validation

- Admission/concurrency/queue suite: 25 passed, including FIFO, cancelled waiter, cancellation during permit handoff, exception release, budget not reset after waiting, BLOCK bypass, distinct error types, privacy and HTTP overload contract.
- Focused admission/async deadline/timeout/retry/validation/telemetry/provider/DataGuard suite: 147 passed.
- Full pytest: 266 passed, 11 failed. Original 128 tests passed; all remaining failures are known SAFE false positives.
- SAFE regression: 17 passed, 11 failed / 28, unchanged and not hidden.
- Stable v2 SHA256: 9b1ab5ef1780b8a152f1ddb634f35cb3d617f70c1ad379c08bcd2ec09e9eadb5; threshold remains 0.51. No V3 runtime or Laya decision changes; no commit/push.

Commands: `.tools/python311/python.exe scripts/provider_admission_eval.py`; `.tools/python311/python.exe -m pytest tests/test_provider_admission.py -q --tb=short`; `.tools/python311/python.exe -m pytest -q --tb=short --junitxml=reports/provider_admission_pytest.xml`; `.tools/python311/python.exe -m pytest tests/test_safe_input_regression.py -q --tb=no`.

Next step: expose provider active/queued counts, overload/deadline counters and admission-wait latency in observability, so deployment capacity can be tuned from measured behavior.
