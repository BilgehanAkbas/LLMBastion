# LLMBastion

[![Tests](https://github.com/BilgehanAkbas/LLMBastion/actions/workflows/tests.yml/badge.svg)](https://github.com/BilgehanAkbas/LLMBastion/actions/workflows/tests.yml)
![Python](https://img.shields.io/badge/Python-3.12%2B-blue)
![License](https://img.shields.io/badge/License-MIT-green)

LLMBastion is a self-hosted, API-first **Turkish-English LLM security gateway** for prompt-injection detection, sensitive-output protection, and security observability. The stable runtime uses the tested hybrid RuleGuard + SemanticGuard v2 pipeline. Experimental candidates that did not pass the project's validation gate are not promoted into the runtime.

## What does LLMBastion do?

LLMBastion sits between your application and the LLM provider.

Instead of sending user input directly to the model, your application sends it
through LLMBastion first.

```text
User / App
    ↓
LLMBastion
    ├── Prompt injection? → BLOCK
    ↓
LLM Provider
    ↓
Sensitive output? → REDACT
    ↓
User
```

## Highlights

- Hybrid input protection with `RuleGuard` + `SemanticGuard v2`
- Multilingual prompt-injection detection for Turkish, English, and mixed-language prompts
- Validation-selected SemanticGuard threshold of `0.51`
- Internal synthetic held-out classifier evaluation: **F1 0.945**, **Recall 0.956**, **Precision 0.935**
- Deterministic sensitive-output protection with `DataGuard v2`
- Provider abstraction behind a common `LLMProvider` interface
- Provider success/failure telemetry and latency tracking
- Per-client API rate limiting for public guard/chat endpoints
- Request-level security telemetry and a local dashboard
- Reproducible model artifact build and GitHub Actions test pipeline

## Public API

The stable API surface is:

```text
POST /v1/guard
POST /v1/chat/completions
```

`POST /v1/guard` inspects a prompt without calling the configured LLM provider.

`POST /v1/chat/completions` is a deliberately small OpenAI-compatible subset:
one non-streaming `user` message is supported today. Security metadata is
returned under the `llmbastion` field. The existing `POST /api/v1/chat`
endpoint remains available for the built-in Playground and backward
compatibility.

The compatibility endpoint uses the provider model configured through
`GROQ_MODEL`. A supplied `model` field must match that configured model;
LLMBastion never claims to have used a different model than the one actually
called upstream.

After starting the API, inspect a prompt without a provider call:

```powershell
$body = @{ input = "Explain how HTTPS works." } | ConvertTo-Json
Invoke-RestMethod -Method Post -Uri http://127.0.0.1:8000/v1/guard -ContentType "application/json" -Body $body
```

For a guarded completion, send one user message:

```powershell
$body = @{ messages = @(@{ role = "user"; content = "Explain how HTTPS works." }) } | ConvertTo-Json -Depth 3
Invoke-RestMethod -Method Post -Uri http://127.0.0.1:8000/v1/chat/completions -ContentType "application/json" -Body $body
```

Both endpoints accept 1–4,000 characters of input. A policy block returns HTTP
`200` with action `BLOCK`; the completion has null content and
`finish_reason: "content_filter"`. An allowed completion returns guarded text
with output action `PASS` or `REDACT`. Streaming, conversation history, tools
and client-supplied system/developer messages are outside this API subset.

## Architecture

```text
User -> RuleGuard -> SemanticGuard v2 -> benign-intent adapter
     -> RiskEngine / Policy -> Groq (async) -> DataGuard -> User
```

Rate limiting precedes input inspection. A blocked request never reaches Groq.
RuleGuard detects explicit injection/bypass attempts; SemanticGuard v2 uses
TF-IDF and logistic regression. RiskEngine blocks on a RuleGuard score of at
least 0.50 or an effective semantic score of at least 0.51.

The adapter neutralizes only the semantic false-positive signal for confidently
recognized editing, tone/style, summarization, previous-draft editing and benign
topic switches. RuleGuard matches, protected instructions, manipulation wording
and encoded/structured payloads prevent an override. Other guards and policy
remain active. API `semantic_score` retains the original model score; audit
metadata records the override, intent family and original score.

DataGuard scans allowed provider responses and redacts supported sensitive
formats. Audit stores detector and provider metadata, not raw user prompts or
provider responses. The provider interface and factory isolate Groq from the
security pipeline.

## SemanticGuard v2 evaluation

SemanticGuard v2 was trained on a **1,200-row synthetic dataset balanced by label**: 600 attack and 600 safe prompts. Language coverage is 540 Turkish, 540 English, and 120 Turkish-English mixed prompts across 15 attack families.

The split is group-aware: paired prompts and detected near-duplicates were kept in the same split to reduce evaluation leakage.

| Split | Rows | Purpose |
| --- | ---: | --- |
| Train | 840 | Model fitting |
| Validation | 180 | Model and threshold selection |
| Held-out test | 180 | Final one-time evaluation |

The selected word-level TF-IDF + Logistic Regression model, at the validation-selected threshold of `0.51`, produced:

```text
Precision: 0.935
Recall:    0.956
F1:        0.945
Accuracy:  0.944
FPR:       0.067
FNR:       0.044

TP: 86  FP: 6  TN: 84  FN: 4
```

These historical internal classifier metrics are not a production guarantee. Held-out labels must not be used to tune future hyperparameters or thresholds.

See the [classifier evaluation report](ml/semantic_guard_v2_report.json) and
[dataset split report](data/llmbastion_dataset/SPLIT_REPORT.json). These results
measure the selected classifier, not the full gateway or benign-intent adapter.

## DataGuard v2

`DataGuard v2` protects allowed LLM responses before they reach the user. It combines pattern matching with deterministic validation where structural validation is available.

- Turkish IBAN candidates are verified with the IBAN MOD-97 checksum.
- Payment-card candidates are verified with the Luhn algorithm to reduce false positives.
- Private-key blocks are redacted as complete blocks.
- Email addresses and supported Turkish mobile-phone formats are redacted.
- Selected API keys and tokens from common provider formats are detected and redacted.
- Audit evidence stores only the output action, finding types, and redaction count.

## Provider layer

The gateway depends on the `LLMProvider` protocol rather than directly on a specific SDK.

```text
Gateway
   |
   v
LLMProvider
   |
   v
Provider Factory
   |
   v
GroqProvider
```

`GroqProvider` is the only implemented provider today. Adding another provider can be done behind the same interface without changing the gateway's security pipeline.

Groq uses a pooled `AsyncGroq` client with awaited calls, bounded admission,
request deadlines and explicit client shutdown. Calls do not use a threadpool.

Provider failures are classified as:

- configuration error: HTTP `503`
- full provider queue: HTTP `503`
- invalid/empty provider response: HTTP `502`
- phase timeout or total provider deadline: HTTP `502`
- unexpected upstream failure: generic HTTP `502`

Defaults are a 20-second phase timeout, a 20-second total provider budget,
zero automatic retries, four active provider operations and 16 queued requests
per application process. Queue waiting shares the total budget. See
[provider admission](docs/PROVIDER_ADMISSION.md),
[async deadlines](docs/PROVIDER_ASYNC_DEADLINE.md) and
[timeout/retry configuration](docs/PROVIDER_TIMEOUT_RETRY.md).

Provider telemetry stores the provider name, success/error status, generic error type, and latency. Raw model responses and low-level SDK exception details are not persisted in provider telemetry.

## Rate limiting

Public POST gateway endpoints are protected by a fixed-window rate limiter. Development can use the in-memory backend; shared deployments can use Redis.

Default configuration:

```text
30 requests / 60 seconds / client IP
```

Rate-limited responses return HTTP `429 Too Many Requests` with:

```text
X-RateLimit-Limit
X-RateLimit-Remaining
X-RateLimit-Reset
Retry-After
```

The limiter deliberately uses the direct socket peer IP rather than trusting `X-Forwarded-For`. Proxy-aware client IP handling should only be enabled behind a configured trusted proxy.

The default raw request-body limit is 32,768 bytes
(`MAX_REQUEST_BODY_BYTES`); larger gateway bodies return HTTP `413`.

## Audit privacy

LLMBastion does not persist full raw prompts or raw model responses as request payloads.

- DataGuard stores finding metadata rather than detected sensitive values.
- Provider telemetry stores generic provider status/error metadata only.
- RuleGuard audit stores rule identifiers and weights only; matched prompt text is removed before persistence.

## Run locally

Requires Python 3.12+. Run commands from the repository root.

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
Copy-Item .env.example .env
```

On Linux/macOS, activate with `source .venv/bin/activate` and copy the environment
template with `cp .env.example .env`. Fill in your Groq key locally; never commit
`.env`.

The copied [.env.example](.env.example) includes all runtime settings. Its
development defaults use SQLite and an in-memory rate limiter. Configure the
provider settings locally:

```text
LLM_PROVIDER=groq
GROQ_API_KEY=
GROQ_MODEL=openai/gpt-oss-20b
RATE_LIMIT_REQUESTS=30
RATE_LIMIT_WINDOW_SECONDS=60
```

Build the already-selected SemanticGuard v2 runtime artifact without touching the held-out test set:

```powershell
python ml/build_semantic_guard_v2_artifact.py
```

Then start the API:

```powershell
uvicorn app.main:app --reload
```

Open:

- Dashboard: `http://127.0.0.1:8000/dashboard`
- Playground: `http://127.0.0.1:8000/playground`
- API docs: `http://127.0.0.1:8000/docs`
- Liveness: `http://127.0.0.1:8000/health`
- Readiness: `http://127.0.0.1:8000/ready`

Readiness checks the database, model artifact, provider configuration and rate
limiter. It does not make a Groq request or verify that the configured key is
accepted upstream. `/v1/guard` can inspect prompts without a Groq key; readiness
and allowed chat requests require one.

## Docker Compose

For the production-shaped local stack (web + PostgreSQL + Redis), set
`GROQ_API_KEY` in `.env` and run:

```powershell
docker compose up --build
```

The Compose stack runs the app in `production` mode, uses PostgreSQL for audit
data, Redis for shared rate limiting, and applies Alembic migrations before
starting Uvicorn.

The API is available at `http://127.0.0.1:8000`. Production disables the
dashboard, Swagger docs and OpenAPI schema; the landing page and Playground
remain available. The Compose credentials are local development defaults;
configure deployment credentials and access controls before external use.

## Tests

Product release gate (only `requirements-dev.txt` is needed):

```powershell
python -m pip install -r requirements-dev.txt
python ml/build_semantic_guard_v2_artifact.py
python -m pytest -m "not research" -q
```

The main repository contains product tests only. Both commands run the complete
product suite:

```powershell
python -m pytest -q
python -m pytest -m "not research" -q
```

Collection checks reject research-only test modules instead of silently hiding
them. No tests are skipped or xfailed. Historical research sources and tests
live in an external archive; see [research status](docs/research/README.md).

GitHub Actions rebuilds the frozen SemanticGuard v2 runtime artifact and runs
the product release gate on pushes and pull requests. See
[test contracts](tests/README.md).

Reported current product suite: `python -m pytest -q` → **369 passed / 0 failed**.
Historical baseline: the product marker command,
`python -m pytest -m "not research" -q`, also reported **369 passed / 0 failed**
before documentation polish at commit `db21325`;
GitHub Actions succeeded on that commit. These are recorded results, not test
runs performed by these documentation changes.

## Limitations

LLMBastion is a focused security gateway, not a complete prompt-injection or data-loss-prevention solution.

- The ML classifier depends on its training distribution and can miss unfamiliar attacks.
- RuleGuard relies on explicit deterministic rules.
- DataGuard v2 protects supported structured formats; it does not yet perform semantic PII/entity detection.
- Groq is the only implemented provider today.
- Development can use the in-memory limiter; shared deployments should use the Redis backend.
- The dashboard is development-only and has no authentication.
- The public API has no built-in client authentication by default; do not expose it to untrusted networks without an access-control layer or trusted reverse proxy.
- The risk policy is a tested OR rule, not a learned multi-signal risk model.
- DataGuard protects provider output; it does not redact sensitive user input before sending it upstream.

SemanticGuard v3+ research is paused and archived outside this product checkout.
It has no runtime, shadow observer or tests here. See
[research status](docs/research/README.md).

## Documentation

- [Product tests and release gate](tests/README.md)
- [Model artifact build](ml/README.md) and [dataset](data/llmbastion_dataset/README.md)
- [Provider admission and queue limits](docs/PROVIDER_ADMISSION.md)
- [Async provider deadline](docs/PROVIDER_ASYNC_DEADLINE.md)
- [Provider timeouts and retries](docs/PROVIDER_TIMEOUT_RETRY.md)
- [Trust boundaries: future design](docs/GATEWAY_TRUST_BOUNDARIES.md)
- [Product repository boundary](docs/REPO_CLEANUP.md) and [research status](docs/research/README.md)
- [Security policy](SECURITY.md)

## Background

The project was motivated in part by [an article on AI agent security](https://medium.com/@bilgehanakbas/yapay-zeka-ajanlar%C4%B1-%C5%9Firketleri-nas%C4%B1l-hackliyor-b6e0308b7cea).

## License

This project is licensed under the [MIT License](LICENSE).
