# Provider timeout / retry

Current admission/queue implementation and latest validation: [Provider admission](PROVIDER_ADMISSION.md). Queue waiting now shares the provider total deadline.

Current implementation supersedes the previous synchronous assessment. See [Async provider deadline](PROVIDER_ASYNC_DEADLINE.md) for the implementation, limits and validation.

Defaults: GROQ_TIMEOUT_SECONDS=20 for network phases (connect at most 5 seconds); GROQ_MAX_RETRIES=0; GROQ_TOTAL_DEADLINE_SECONDS=20 for the entire async provider operation including retries/backoff. Manual retry override accepts 0–2. Defaults permit one SDK generation attempt; overrides permit at most 2/3 while total deadline remains.

Provider calls directly await AsyncGroq and share a reusable HTTPX async client on the application loop. No provider threadpool or detached background generation remains. Deadline failure uses existing generic 502/audit ERROR behavior and skips DataGuard. Local HTTP cancellation was verified against synthetic transport and a real local TCP socket. Remote provider computation/billing cancellation is not guaranteed.

Synthetic latency metadata is in reports/provider_latency_policy.json. It uses 10 ms scheduled attempt delays and controlled 20 ms retry backoff; actual elapsed values include OS timer scheduling and are not production latency or an actual 20-second timeout measurement.
