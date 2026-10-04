# Provider admission and bounded queue

LLMBastion bounds provider work per application process/event loop. Admission
runs after input policy allows a request; blocked requests never enter the queue
or call Groq.

## Configuration

| Setting | Default | Meaning |
| --- | ---: | --- |
| `GROQ_MAX_CONCURRENT_REQUESTS` | `4` | Maximum active provider operations; must be positive |
| `GROQ_MAX_QUEUED_REQUESTS` | `16` | Maximum waiting operations; must be nonnegative |
| `GROQ_TOTAL_DEADLINE_SECONDS` | `20` | Shared budget for queue wait, setup, network waits, retries and backoff |

A queue limit of `0` rejects immediately when all active slots are occupied.
Each worker has its own limits; multiple workers multiply available capacity.
Redis-backed ingress rate limiting is separate from provider admission.

## Flow and ownership

```text
Input guards -> policy -> BLOCK: return without provider work
                       -> ALLOW: total provider deadline
                                 -> admission slot
                                 -> AsyncGroq generation / retries / response validation
                                 -> release slot
                                 -> DataGuard -> response
```

`ProviderAdmission` uses an `asyncio.BoundedSemaphore` and a waiter counter.
Admission checking and counting have no await gap. Pending handoffs count as
occupied capacity, so new arrivals do not overtake existing waiters. A woken
waiter stays in the queue count until it resumes.

A slot covers generation, retries and backoff. Completion, exceptions and
cancellation release it in `finally`; cancelled waiters remove their queue
count. Admission is recreated at lifespan startup for the current event loop.
Independent concurrent applications must not share the global gateway runtime.
Direct calls to `provider.generate` bypass gateway admission.

Queue waiting consumes the same total deadline as generation; acquiring a slot
does not reset it. The gateway checks expiry again before dispatch after a
handoff. This cooperative provider budget excludes input guards, database work,
DataGuard and audit persistence. It does not bound ingress connections or remote
provider computation. See [async deadlines](PROVIDER_ASYNC_DEADLINE.md).

## Error contract

| Condition | HTTP | Audit action | Provider `error_type` |
| --- | ---: | --- | --- |
| Provider failure / upstream 429 or 500 | 502 | ERROR | `request_failed` |
| SDK phase timeout | 502 | ERROR | `provider_timeout` |
| Total deadline during generation/backoff | 502 | ERROR | `deadline_exceeded` |
| Total deadline while queued / before dispatch | 502 | ERROR | `admission_deadline_exceeded` |
| Queue full | 503 | ERROR | `overloaded` |
| Missing provider configuration | 503 | ERROR | `configuration` |
| Invalid or empty completion | 502 | ERROR | `invalid_response` |

In development, ordinary provider failures use `LLM provider request failed`.
Invalid completions use `LLM provider returned an invalid response`. Overload
uses `LLM provider busy` and structured `service_unavailable`. Production
sanitizes all HTTP `502` messages to `Upstream service error` and all HTTP `503`
messages to `Service temporarily unavailable`; audit error types remain distinct.

DataGuard runs only after a successful, validated provider response. Audit and
structured application logs retain generic status/error metadata, not raw
prompts, responses, credentials or SDK exception messages.

## Validation

From the repository root, after the [test setup](../README.md#tests):

```powershell
python -m pytest tests/test_provider_admission.py tests/test_provider_async_deadline.py tests/test_provider_timeouts.py -q
python scripts/provider_admission_eval.py
```

The admission tests cover queue bounds, FIFO handoffs, cancelled waiters,
cancellation during handoff, exception release, deadline preservation, BLOCK
bypass, error types, privacy and the HTTP overload contract.

The evaluator uses real AsyncGroq/HTTPX with controlled local async transport;
it makes no Groq network calls. Guards and audit persistence are mocked to
isolate policy, admission, deadline, provider errors and DataGuard. Scenarios
cover below/above capacity, queue overflow, queued deadlines, provider timeout
and mixed success/cancellation. These are correctness checks, not production
throughput benchmarks.

The evaluator generates `reports/provider_admission_load.json` locally; that
ignored output is not shipped in the checkout. Use the [product release gate](../README.md#tests)
for the recorded baseline and current full-suite command. Earlier migration
counts and SAFE failures describe superseded implementations, not this release.
