from pathlib import Path

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

router = APIRouter(tags=["Public"])

BASE_DIR = Path(__file__).resolve().parent.parent
templates = Jinja2Templates(
    directory=str(BASE_DIR / "templates")
)


@router.get(
    "/",
    response_class=HTMLResponse,
    include_in_schema=False,
)
def landing(request: Request):
    return templates.TemplateResponse(
        request,
        "landing.html",
    )
