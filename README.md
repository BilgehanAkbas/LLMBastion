# LLMBastion

[![Tests](https://github.com/BilgehanAkbas/LLMBastion/actions/workflows/tests.yml/badge.svg)](https://github.com/BilgehanAkbas/LLMBastion/actions/workflows/tests.yml)
![Python](https://img.shields.io/badge/Python-3.12%2B-blue)
![License](https://img.shields.io/badge/License-MIT-green)

LLMBastion is a prototype **LLM security gateway** that combines deterministic rules and machine learning to detect prompt-injection attacks before they reach an LLM, enforce risk-based policy decisions, protect sensitive output data, and provide security observability.

## Highlights

- Hybrid input protection with `RuleGuard` + `SemanticGuard v2`
- Multilingual prompt-injection detection for Turkish, English, and mixed-language prompts
- Validation-selected SemanticGuard threshold of `0.51`
- Held-out evaluation: **F1 0.945**, **Recall 0.956**, **Precision 0.935**
- Deterministic sensitive-output protection with `DataGuard v2`
- Provider abstraction behind a common `LLMProvider` interface
- Provider success/failure telemetry and latency tracking
- Per-client API rate limiting for `POST /api/v1/chat`
- Request-level security telemetry and a local dashboard
- Reproducible model artifact build and GitHub Actions test pipeline

## Architecture

```text
User Prompt
    |
    v
Rate Limiter
    |
    +----------------------+
    |                      |
    v                      v
RuleGuard             SemanticGuard v2
Regex rules           TF-IDF + Logistic Regression
    |                      |
    +----------+-----------+
               |
               v
           RiskEngine
               |
            Policy
          /        \
       BLOCK      ALLOW
         |          |
       Audit    LLMProvider
                    |
                    v
              Provider Factory
                    |
                   Groq
                    |
                    v
               DataGuard v2
                    |
                  Audit
                    |
                   User
```

A blocked request never reaches the LLM provider. An allowed request is sent through the configured provider, then the model response is scanned by `DataGuard v2` before it is returned to the user.

- `RuleGuard` detects explicit instruction overrides, system-prompt extraction, jailbreaks, and security-bypass attempts.
- `SemanticGuard v2` estimates prompt-injection probability with a multilingual TF-IDF + Logistic Regression classifier.
- `RiskEngine` blocks when either guard meets its tested threshold: RuleGuard `>= 0.50` or SemanticGuard v2 `>= 0.51`.
- `LLMProvider` defines the minimal provider contract; provider construction is isolated behind a factory.
- `DataGuard v2` redacts emails, Turkish mobile numbers, JWTs, selected provider tokens, private-key blocks, validated Turkish IBANs, and Luhn-valid payment-card numbers.
- Provider status and latency are recorded without storing raw provider responses.
- The local dashboard exposes request, detector, provider, redaction, error, and latency telemetry.

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

These figures are an internal, leakage-controlled evaluation result—not a production guarantee. The held-out labels are included for reproducibility and must not be used to tune future hyperparameters or thresholds.

The full report is at `ml/semantic_guard_v2_report.json`; split details are at `data/llmbastion_dataset/SPLIT_REPORT.json`.

## DataGuard v2

`DataGuard v2` protects allowed LLM responses before they reach the user. It combines pattern matching with deterministic validation where structural validation is available.

- Turkish IBAN candidates are verified with the IBAN MOD-97 checksum.
- Payment-card candidates are verified with the Luhn algorithm to reduce false positives.
- Private-key blocks are redacted as complete blocks.
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

Provider SDK calls are executed through Starlette's threadpool so synchronous upstream SDK calls do not block FastAPI's async event loop.

Provider failures are classified as:

- configuration error → HTTP `503`
- invalid/empty provider response → HTTP `502`
- unexpected upstream failure → generic HTTP `502`

Provider telemetry stores the provider name, success/error status, generic error type, and latency. Raw model responses and low-level SDK exception details are not persisted in provider telemetry.

## Rate limiting

`POST /api/v1/chat` is protected by a process-local fixed-window rate limiter.

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

The current implementation is intentionally in-memory and single-process. Multi-instance production deployments should use a shared limiter such as Redis or an API gateway.

## Audit privacy

LLMBastion does not persist full raw prompts or raw model responses as request payloads.

- DataGuard stores finding metadata rather than detected sensitive values.
- Provider telemetry stores generic provider status/error metadata only.
- RuleGuard may store the specific matched substring used as rule evidence.

## Run locally

Requires Python 3.12+.

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install -r requirements.txt
Copy-Item .env.example .env
```

Example `.env`:

```text
LLM_PROVIDER=groq
GROQ_API_KEY=
GROQ_MODEL=openai/gpt-oss-20b
RATE_LIMIT_REQUESTS=30
RATE_LIMIT_WINDOW_SECONDS=60
```

Build the already-selected SemanticGuard v2 runtime artifact without touching the held-out test set:

```powershell
python ml\build_semantic_guard_v2_artifact.py
```

Then start the API:

```powershell
uvicorn app.main:app --reload
```

Open:

- Dashboard: `http://127.0.0.1:8000/dashboard`
- API docs: `http://127.0.0.1:8000/docs`

## Tests

```powershell
python -m pytest -q
```

Final local verification: **74 passed**.

GitHub Actions builds the runtime artifact and runs the test suite on pushes and pull requests.

## Limitations

LLMBastion is a prototype, not a complete prompt-injection or data-loss-prevention solution.

- The ML classifier depends on its training distribution and can miss unfamiliar attacks.
- RuleGuard relies on explicit deterministic rules.
- DataGuard v2 protects supported structured formats; it does not yet perform semantic PII/entity detection.
- Groq is the only implemented provider today.
- The rate limiter is process-local and not suitable for multi-instance production deployments.
- The dashboard is intended for local development and has no authentication.
- The risk policy is a tested OR rule, not a learned multi-signal risk model.

## Background

The project was motivated in part by [Yapay Zeka Ajanları Şirketleri Nasıl Hackliyor](https://medium.com/@bilgehanakbas/yapay-zeka-ajanlar%C4%B1-%C5%9Firketleri-nas%C4%B1l-hackliyor-b6e0308b7cea), an article on the security risks around AI agents.

## License

This project is licensed under the [MIT License](LICENSE).
