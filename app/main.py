from pathlib import Path

from fastapi import FastAPI
from fastapi.openapi.docs import get_swagger_ui_html
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from starlette.responses import RedirectResponse

from .database import engine
from .models import Base
from .routers.dashboard import router as dashboard_router
from .routers.gateway import router as gateway_router

BASE_DIR = Path(__file__).resolve().parent

app = FastAPI(
    title="LLMBastion",
    description="LLM security gateway for prompt and output protection.",
    version="0.2.0",
    docs_url=None,
)

app.mount(
    "/static",
    StaticFiles(directory=str(BASE_DIR / "static")),
    name="static",
)

Base.metadata.create_all(bind=engine)


@app.get("/")
def read_root():
    return RedirectResponse(url="/dashboard")


@app.get("/health")
def health():
    return {
        "status": "ok",
        "service": "LLMBastion",
        "version": "0.2.0",
    }


@app.get("/docs", include_in_schema=False)
def custom_swagger_docs():
    swagger = get_swagger_ui_html(
        openapi_url=app.openapi_url,
        title=f"{app.title} - API Docs",
    )

    html = swagger.body.decode("utf-8")
    dashboard_button = '''
    <a
        href="/dashboard"
        style="
            position: fixed;
            top: 10px;
            right: 18px;
            z-index: 9999;
            background: #1f2937;
            color: white;
            padding: 8px 14px;
            border-radius: 6px;
            text-decoration: none;
            font-family: Arial, sans-serif;
            font-size: 14px;
            box-shadow: 0 2px 8px rgba(0,0,0,.18);
        "
    >
        ← Dashboard
    </a>
    '''
    html = html.replace("</body>", f"{dashboard_button}</body>")

    return HTMLResponse(content=html)


app.include_router(gateway_router)
app.include_router(dashboard_router)
