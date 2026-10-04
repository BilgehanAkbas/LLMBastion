# Provider timeouts and retries

The provider uses awaited AsyncGroq calls and a reusable HTTPX async client.
Timeouts operate at two levels:

| Setting | Default | Behavior |
| --- | ---: | --- |
| `GROQ_TIMEOUT_SECONDS` | `20` | Per-network-phase timeout; connect is at most 5 seconds |
| `GROQ_TOTAL_DEADLINE_SECONDS` | `20` | Shared provider budget, including queue wait, setup, retries and backoff |
| `GROQ_MAX_RETRIES` | `0` | No automatic retries; explicit overrides accept 1 or 2 |

Timeout values must be finite and positive. Zero retries permits one SDK
attempt; overrides allow at most two or three attempts before the total
budget expires. A retry may initiate another upstream generation.

Phase and total-deadline failures return generic HTTP `502`, record audit
`ERROR`, and skip DataGuard. Queue overflow returns HTTP `503`. See
[admission error types](PROVIDER_ADMISSION.md#error-contract) and
[async deadline scope](PROVIDER_ASYNC_DEADLINE.md#scope-and-client-lifetime).
Local cancellation does not guarantee that remote computation or billing stops.

## Validation

After the [test setup](../README.md#tests), run:

```powershell
python -m pytest tests/test_provider_timeouts.py tests/test_provider_async_deadline.py -q
python scripts/provider_latency_eval.py
```

The offline evaluator generates `reports/provider_latency_policy.json` locally.
It uses synthetic 10 ms attempt delays and controlled 20 ms retry backoff;
measured elapsed time includes OS scheduling. It does not measure production
latency or an actual 20-second timeout. Generated reports are ignored and are
not included in the checkout.
