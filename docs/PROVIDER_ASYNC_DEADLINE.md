# Async provider deadline

The gateway awaits `GroqProvider.generate`, which uses a pooled `AsyncGroq`
client and HTTPX async I/O. Generation and client shutdown do not use a
threadpool or detached background task. Queue admission shares the total
provider deadline; see [provider admission](PROVIDER_ADMISSION.md).

## Configuration and error contract

| Setting | Default | Scope |
| --- | ---: | --- |
| `GROQ_TIMEOUT_SECONDS` | `20` | Read/write/pool phase timeout; connect uses the smaller of 5 seconds and this value |
| `GROQ_TOTAL_DEADLINE_SECONDS` | `20` | Total gateway provider-operation budget, including admission, setup, waits, retries and backoff |
| `GROQ_MAX_RETRIES` | `0` | SDK retry limit; accepts 0–2 |

Timeout values must be finite and positive. The default permits one SDK
attempt; retry overrides permit at most two or three attempts while the total
budget remains.

The gateway uses `asyncio.timeout` around admission and generation. It checks
expiry after slot acquisition before dispatch. Generation/backoff expiry records
`deadline_exceeded`; queue/pre-dispatch expiry records
`admission_deadline_exceeded`. SDK phase timeout records `provider_timeout`.
All return a generic HTTP `502` provider failure, audit action `ERROR`, and skip
DataGuard. Queue overflow instead returns `503`.

External task cancellation propagates. It is not swallowed or converted into a
provider retry. Cancellation of one request does not close the shared client or
cancel peer requests.

## Scope and client lifetime

This is a cooperative provider-operation budget, not a whole HTTP-request
or hard real-time deadline. Input guards, database work, DataGuard and audit
persistence are outside it. Blocking event-loop work can delay cancellation,
and cleanup takes time. Local HTTP cancellation cannot guarantee that remote
Groq computation or billing stops.

One lazy client is reused per provider on the application event loop. Client
construction contains no await, so concurrent tasks cannot interleave it.
Application shutdown detaches and awaits client close after requests drain.
Do not share a live provider across independent concurrent applications or
event loops.

## Validation

After the [test setup](../README.md#tests), run:

```powershell
python -m pytest tests/test_provider_async_deadline.py tests/test_provider_timeouts.py tests/test_groq_provider.py -q
```

The offline tests cover normal completion, cancellation before headers and
during body reads, retry/backoff cancellation, peer isolation, client reuse,
shutdown and cleanup. A local TCP server test stalls a response body and checks
that HTTPX closes the connection on deadline. No slow or fault-injected requests
are sent to Groq.

See the [product release gate](../README.md#tests) for the recorded baseline and
full-suite command. Historical migration test counts and pre-adapter SAFE
failures are not current release results.
