from pathlib import Path

from fastapi import FastAPI
from fastapi.openapi.docs import get_swagger_ui_html
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles

from .core.config import (
    APP_ENV,
    RATE_LIMIT_REQUESTS,
    RATE_LIMIT_WINDOW_SECONDS,
)
from .database import engine
from .models import Base
from .routers.dashboard import router as dashboard_router
from .routers.gateway import router as gateway_router
from .routers.playground import router as playground_router
from .routers.public import router as public_router
from .services.rate_limiter import (
    ChatRateLimitMiddleware,
    FixedWindowRateLimiter,
)

BASE_DIR = Path(__file__).resolve().parent


def create_app(app_env: str = APP_ENV) -> FastAPI:
    normalized_env = app_env.strip().lower()
    if normalized_env not in {"development", "production"}:
        raise ValueError(
            "app_env must be either 'development' or 'production'"
        )

    is_development = normalized_env == "development"

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

    application.add_middleware(
        ChatRateLimitMiddleware,
        limiter=FixedWindowRateLimiter(
            limit=RATE_LIMIT_REQUESTS,
            window_seconds=RATE_LIMIT_WINDOW_SECONDS,
        ),
    )

    application.mount(
        "/static",
        StaticFiles(directory=str(BASE_DIR / "static")),
        name="static",
    )

    Base.metadata.create_all(bind=engine)

    @application.get("/health")
    def health():
        return {
            "status": "ok",
            "service": "LLMBastion",
            "version": "0.2.0",
            "environment": normalized_env,
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
