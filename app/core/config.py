import os

from dotenv import load_dotenv

load_dotenv()


APP_ENV = (
    os.getenv("APP_ENV", "development")
    .strip()
    .lower()
)

if APP_ENV not in {"development", "production"}:
    raise ValueError(
        "APP_ENV must be either 'development' or 'production'"
    )

IS_DEVELOPMENT = APP_ENV == "development"
IS_PRODUCTION = APP_ENV == "production"


LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO").strip().upper()
if LOG_LEVEL not in {
    "DEBUG",
    "INFO",
    "WARNING",
    "ERROR",
    "CRITICAL",
}:
    raise ValueError(
        "LOG_LEVEL must be DEBUG, INFO, WARNING, ERROR, or CRITICAL"
    )


DATABASE_URL = os.getenv(
    "DATABASE_URL",
    "sqlite:///./llmbastion.db",
).strip()

if not DATABASE_URL:
    raise ValueError("DATABASE_URL cannot be empty")

if IS_PRODUCTION and DATABASE_URL.startswith("sqlite"):
    raise ValueError(
        "Production requires a PostgreSQL DATABASE_URL"
    )


LLM_PROVIDER = os.getenv("LLM_PROVIDER", "groq").strip().lower()

GROQ_API_KEY = os.getenv("GROQ_API_KEY")
GROQ_MODEL = os.getenv("GROQ_MODEL", "openai/gpt-oss-20b")


RATE_LIMIT_REQUESTS = int(os.getenv("RATE_LIMIT_REQUESTS", "30"))
RATE_LIMIT_WINDOW_SECONDS = int(
    os.getenv("RATE_LIMIT_WINDOW_SECONDS", "60")
)

RATE_LIMIT_BACKEND = os.getenv(
    "RATE_LIMIT_BACKEND",
    "redis" if IS_PRODUCTION else "memory",
).strip().lower()

if RATE_LIMIT_BACKEND not in {"memory", "redis"}:
    raise ValueError(
        "RATE_LIMIT_BACKEND must be either 'memory' or 'redis'"
    )

REDIS_URL = os.getenv("REDIS_URL", "").strip() or None

if RATE_LIMIT_BACKEND == "redis" and not REDIS_URL:
    raise ValueError(
        "REDIS_URL is required when RATE_LIMIT_BACKEND=redis"
    )


MAX_REQUEST_BODY_BYTES = int(
    os.getenv("MAX_REQUEST_BODY_BYTES", "32768")
)

if RATE_LIMIT_REQUESTS < 1:
    raise ValueError("RATE_LIMIT_REQUESTS must be at least 1")
if RATE_LIMIT_WINDOW_SECONDS < 1:
    raise ValueError(
        "RATE_LIMIT_WINDOW_SECONDS must be at least 1"
    )
if MAX_REQUEST_BODY_BYTES < 1024:
    raise ValueError(
        "MAX_REQUEST_BODY_BYTES must be at least 1024"
    )
