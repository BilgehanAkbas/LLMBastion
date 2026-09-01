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


LLM_PROVIDER = os.getenv("LLM_PROVIDER", "groq").strip().lower()

GROQ_API_KEY = os.getenv("GROQ_API_KEY")
GROQ_MODEL = os.getenv("GROQ_MODEL", "openai/gpt-oss-20b")


RATE_LIMIT_REQUESTS = int(os.getenv("RATE_LIMIT_REQUESTS", "30"))
RATE_LIMIT_WINDOW_SECONDS = int(
    os.getenv("RATE_LIMIT_WINDOW_SECONDS", "60")
)

if RATE_LIMIT_REQUESTS < 1:
    raise ValueError("RATE_LIMIT_REQUESTS must be at least 1")
if RATE_LIMIT_WINDOW_SECONDS < 1:
    raise ValueError(
        "RATE_LIMIT_WINDOW_SECONDS must be at least 1"
    )
