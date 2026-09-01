from pathlib import Path

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

router = APIRouter(tags=["Playground"])

BASE_DIR = Path(__file__).resolve().parent.parent
templates = Jinja2Templates(
    directory=str(BASE_DIR / "templates")
)


@router.get(
    "/playground",
    response_class=HTMLResponse,
    include_in_schema=False,
)
def playground(request: Request):
    return templates.TemplateResponse(
    request,
    "playground.html",
)