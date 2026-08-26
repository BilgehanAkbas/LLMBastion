from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.staticfiles import StaticFiles
from starlette import status
from starlette.responses import RedirectResponse

from .database import engine
from .models import Base
from .routers.auth import router as auth_router
from .routers.todo import router as todo_router
from .routers.gateway import router as gateway_router

BASE_DIR = Path(__file__).resolve().parent

app = FastAPI(
    title="LLMBastion",
    description="Secure baseline for an evolving LLM security gateway.",
    version="0.2.0",
)

app.mount(
    "/static",
    StaticFiles(directory=str(BASE_DIR / "static")),
    name="static",
)

Base.metadata.create_all(bind=engine)


@app.get("/")
def read_root(request: Request):
    return RedirectResponse(
        url="/todo/todo-page",
        status_code=status.HTTP_302_FOUND,
    )


@app.get("/health")
def health():
    return {
        "status": "ok",
        "service": "LLMBastion",
        "version": "0.2.0",
    }


app.include_router(auth_router)
app.include_router(todo_router)
app.include_router(gateway_router)
