import logging
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.openapi.docs import get_swagger_ui_html
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy import text

from .core.config import (
    APP_ENV,
    GROQ_API_KEY,
    LLM_PROVIDER,
    LOG_LEVEL,
    MAX_REQUEST_BODY_BYTES,
    RATE_LIMIT_BACKEND,
    RATE_LIMIT_REQUESTS,
    RATE_LIMIT_WINDOW_SECONDS,
    REDIS_URL,
)
from .core.errors import install_error_handlers
from .core.observability import configure_logging, log_event
from .database import SessionLocal, engine
from .models import Base
from .routers.dashboard import router as dashboard_router
from .routers.gateway import (
    router as gateway_router,
    semantic_guard,
)
from .routers.playground import router as playground_router
from .routers.public import router as public_router
from .services.rate_limiter import (
    ChatRateLimitMiddleware,
    RateLimiter,
    build_rate_limiter,
)
from .services.request_context import RequestContextMiddleware
from .services.request_size import RequestBodyLimitMiddleware
from .services.security_headers import SecurityHeadersMiddleware

configure_logging(LOG_LEVEL)
logger = logging.getLogger(__name__)

BASE_DIR = Path(__file__).resolve().parent


def _check_database_ready() -> None:
    db = SessionLocal()
    try:
        db.execute(text("SELECT 1"))
    finally:
        db.close()


def _check_provider_configuration() -> None:
    # Groq is the only implemented provider today. This is intentionally a
    # local configuration check; /ready never makes a paid/network LLM call.
    if LLM_PROVIDER == "groq" and not GROQ_API_KEY:
        raise RuntimeError(
            "GROQ_API_KEY is not configured"
        )


def _check_rate_limiter_ready(
    limiter: RateLimiter,
) -> None:
    if not limiter.ping():
        raise RuntimeError(
            "Rate limiter backend is not ready"
        )


def create_app(
    app_env: str = APP_ENV,
    *,
    max_request_body_bytes: int = MAX_REQUEST_BODY_BYTES,
    rate_limiter: RateLimiter | None = None,
) -> FastAPI:
    normalized_env = app_env.strip().lower()
    if normalized_env not in {"development", "production"}:
        raise ValueError(
            "app_env must be either 'development' or 'production'"
        )
    if max_request_body_bytes < 1:
        raise ValueError(
            "max_request_body_bytes must be at least 1"
        )

    is_development = normalized_env == "development"

    limiter = rate_limiter or build_rate_limiter(
        backend=RATE_LIMIT_BACKEND,
        limit=RATE_LIMIT_REQUESTS,
        window_seconds=RATE_LIMIT_WINDOW_SECONDS,
        redis_url=REDIS_URL,
    )

    application = FastAPI(
        title="LLMBastion",
        description=(
            "LLM security gateway for prompt and output protection."
        ),
        version="0.2.0",
        docs_url=None,
        redoc_url=None,
        openapi_url=(
            "/openapi.json"
            if is_development
            else None
        ),
    )

    application.state.app_env = normalized_env
    application.state.is_development = is_development
    application.state.max_request_body_bytes = (
        max_request_body_bytes
    )
    application.state.rate_limiter = limiter

    install_error_handlers(application)

    # add_middleware inserts new middleware outside previous user middleware.
    # Desired request order:
    # request context -> security headers -> rate limit -> body limit -> routes.
    application.add_middleware(
        RequestBodyLimitMiddleware,
        max_bytes=max_request_body_bytes,
    )
    application.add_middleware(
        ChatRateLimitMiddleware,
        limiter=limiter,
    )
    application.add_middleware(
        SecurityHeadersMiddleware,
        is_development=is_development,
    )
    application.add_middleware(
        RequestContextMiddleware,
    )

    application.mount(
        "/static",
        StaticFiles(directory=str(BASE_DIR / "static")),
        name="static",
    )

    # Development remains zero-setup. Production schema changes are handled by
    # Alembic so deploys do not silently mutate the database at app import.
    if is_development:
        Base.metadata.create_all(bind=engine)

    @application.get("/favicon.ico", include_in_schema=False)
    def legacy_favicon():
        return RedirectResponse(
            url="/static/favicon.svg",
            status_code=307,
        )

    @application.get("/health")
    def health():
        return {
            "status": "ok",
            "service": "LLMBastion",
            "version": "0.2.0",
            "environment": normalized_env,
        }

    @application.get("/ready")
    def ready():
        try:
            _check_database_ready()
            semantic_guard.ensure_ready()
            _check_provider_configuration()
            _check_rate_limiter_ready(limiter)
        except Exception as exc:
            log_event(
                logger,
                logging.ERROR,
                "readiness.failed",
                environment=normalized_env,
                exc_info=(
                    type(exc),
                    exc,
                    exc.__traceback__,
                ),
            )
            raise HTTPException(
                status_code=503,
                detail="Readiness check failed",
            ) from exc

        return {
            "status": "ready",
            "service": "LLMBastion",
            "version": "0.2.0",
            "environment": normalized_env,
            "checks": {
                "database": "ok",
                "semantic_guard": "ok",
                "provider_config": "ok",
                "rate_limiter": "ok",
            },
        }

    application.include_router(public_router)
    application.include_router(gateway_router)
    application.include_router(playground_router)

    if is_development:
        application.include_router(dashboard_router)

        @application.get(
            "/docs",
            include_in_schema=False,
        )
        def custom_swagger_docs():
            swagger = get_swagger_ui_html(
                openapi_url=application.openapi_url,
                title=f"{application.title} - API Docs",
            )

            html = swagger.body.decode("utf-8")
            navigation = """
            <div
                style="
                    position: fixed;
                    top: 10px;
                    right: 18px;
                    z-index: 9999;
                    display: flex;
                    gap: 8px;
                    font-family: Arial, sans-serif;
                "
            >
                <a
                    href="/playground"
                    style="
                        background: #4f46e5;
                        color: white;
                        padding: 8px 14px;
                        border-radius: 6px;
                        text-decoration: none;
                        font-size: 14px;
                    "
                >
                    Playground
                </a>
                <a
                    href="/dashboard"
                    style="
                        background: #1f2937;
                        color: white;
                        padding: 8px 14px;
                        border-radius: 6px;
                        text-decoration: none;
                        font-size: 14px;
                    "
                >
                    Dashboard
                </a>
            </div>
            """
            html = html.replace(
                "</body>",
                f"{navigation}</body>",
            )
            return HTMLResponse(content=html)

    return application


app = create_app()
