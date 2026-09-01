import os

from dotenv import load_dotenv

load_dotenv()

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
