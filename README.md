# LLMBastion

LLMBastion is an evolving LLM security gateway project built on top of a FastAPI + SQLite + Gemini application originally developed during the Yapay Zeka ve Teknoloji Akademisi training.

The long-term goal is to place a security layer between client applications and LLM providers, with prompt-injection detection, risk-based decisions, output protection, audit logging, and security observability.

Repository: https://github.com/BilgehanAkbas/LLMBastion

## Current state — secure baseline

This version is the cleaned and hardened project baseline before the first LLM guard is introduced.

### Security fixes included

- Real `.env` files and local SQLite databases are excluded from the repository.
- `.gitignore` and a safe `.env.example` are included.
- JWT secrets are no longer hard-coded and are read from `JWT_SECRET_KEY`.
- Registration does not accept a client-controlled `role`; new users are created as `user`.
- Todo edit routes verify resource ownership.
- Docker and Python package paths are aligned around `app.main:app`.
- The original Todo + Gemini flow is intentionally preserved so it can later act as a before/after demo client for LLMBastion.

## Security note

This ZIP contains no real API keys or JWT secrets.

If a previous Gemini API key was ever committed to a public repository, revoke/delete that key in Google AI Studio and use a new key only in your local `.env`.

This ZIP does not contain Git history. Rewriting/removing secrets from old remote commits is a separate Git-history operation.

## Setup

Python 3.11+ is supported. Using a project-local virtual environment is recommended.

Create a virtual environment:

```bash
python -m venv .venv
```

Windows PowerShell:

```powershell
.\.venv\Scripts\Activate.ps1
```

Linux/macOS:

```bash
source .venv/bin/activate
```

Install dependencies:

```bash
python -m pip install --upgrade pip
pip install -r requirements.txt
```

Create your local environment file:

Windows PowerShell:

```powershell
Copy-Item .env.example .env
```

Linux/macOS:

```bash
cp .env.example .env
```

Generate a JWT secret:

```bash
python -c "import secrets; print(secrets.token_urlsafe(64))"
```

Then fill your local `.env`:

```env
GOOGLE_API_KEY=YOUR_NEW_LOCAL_KEY
JWT_SECRET_KEY=YOUR_RANDOM_SECRET
GEMINI_MODEL=gemini-pro
```

Never commit `.env`.

Run the application:

```bash
uvicorn app.main:app --reload
```

Open:

- App: `http://127.0.0.1:8000`
- Swagger: `http://127.0.0.1:8000/docs`
- Health: `http://127.0.0.1:8000/health`

## Docker

```bash
docker compose up --build
```

The app will be available at `http://127.0.0.1:8000`.

## Next development slice

The first LLMBastion security feature will be:

```text
POST /api/v1/chat
        ↓
    Rule Guard
        ↓
  ALLOW / BLOCK
        ↓
      Gemini
```

This keeps the first milestone intentionally small and demonstrable.
