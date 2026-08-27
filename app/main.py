from pathlib import Path

from fastapi import FastAPI
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


app.include_router(gateway_router)
app.include_router(dashboard_router)
