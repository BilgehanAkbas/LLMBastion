from pathlib import Path
from typing import Annotated

import google.generativeai as genai
import markdown
from bs4 import BeautifulSoup
from fastapi import APIRouter, Depends, HTTPException, Path as ApiPath, Request
from fastapi.templating import Jinja2Templates
from langchain_core.messages import HumanMessage
from langchain_google_genai import ChatGoogleGenerativeAI
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session
from starlette import status
from starlette.responses import RedirectResponse

from ..core.config import GEMINI_MODEL, GOOGLE_API_KEY
from ..database import SessionLocal
from ..models import Todo
from .auth import get_current_user

router = APIRouter(
    prefix="/todo",
    tags=["Todo Demo"],
)

TEMPLATES_DIR = Path(__file__).resolve().parents[1] / "templates"
templates = Jinja2Templates(directory=str(TEMPLATES_DIR))


class TodoRequest(BaseModel):
    title: str = Field(min_length=3)
    description: str = Field(min_length=3, max_length=1000)
    priority: int = Field(gt=0, lt=6)
    complete: bool


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


db_dependency = Annotated[Session, Depends(get_db)]
user_dependency = Annotated[dict, Depends(get_current_user)]


def redirect_to_login():
    response = RedirectResponse(
        url="/auth/login-page",
        status_code=status.HTTP_302_FOUND,
    )
    response.delete_cookie("access_token")
    return response


async def get_user_from_cookie(request: Request):
    token = request.cookies.get("access_token")
    if not token:
        return None

    try:
        return await get_current_user(token)
    except HTTPException:
        return None


@router.get("/todo-page")
async def render_todo_page(
    request: Request,
    db: db_dependency,
):
    user = await get_user_from_cookie(request)
    if user is None:
        return redirect_to_login()

    todos = (
        db.query(Todo)
        .filter(Todo.owner_id == user.get("id"))
        .all()
    )

    return templates.TemplateResponse(
        "todo.html",
        {
            "request": request,
            "todos": todos,
            "user": user,
        },
    )


@router.get("/add-todo-page")
async def render_add_todo_page(request: Request):
    user = await get_user_from_cookie(request)
    if user is None:
        return redirect_to_login()

    return templates.TemplateResponse(
        "add-todo.html",
        {
            "request": request,
            "user": user,
        },
    )


@router.get("/edit-todo-page/{todo_id}")
async def render_edit_todo_page(
    request: Request,
    todo_id: int,
    db: db_dependency,
):
    user = await get_user_from_cookie(request)
    if user is None:
        return redirect_to_login()

    todo = (
        db.query(Todo)
        .filter(
            Todo.id == todo_id,
            Todo.owner_id == user.get("id"),
        )
        .first()
    )

    if todo is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Todo not found",
        )

    return templates.TemplateResponse(
        "edit-todo.html",
        {
            "request": request,
            "todo": todo,
            "user": user,
        },
    )


@router.get("/")
async def read_all(
    user: user_dependency,
    db: db_dependency,
):
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED
        )

    return (
        db.query(Todo)
        .filter(Todo.owner_id == user.get("id"))
        .all()
    )


@router.get(
    "/todo/{todo_id}",
    status_code=status.HTTP_200_OK,
)
async def read_by_id(
    user: user_dependency,
    db: db_dependency,
    todo_id: int = ApiPath(gt=0),
):
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED
        )

    todo = (
        db.query(Todo)
        .filter(
            Todo.id == todo_id,
            Todo.owner_id == user.get("id"),
        )
        .first()
    )

    if todo is not None:
        return todo

    raise HTTPException(
        status_code=status.HTTP_404_NOT_FOUND,
        detail="Todo not found",
    )


@router.post(
    "/todo",
    status_code=status.HTTP_201_CREATED,
)
async def create_todo(
    user: user_dependency,
    db: db_dependency,
    todo_request: TodoRequest,
):
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED
        )

    todo = Todo(
        **todo_request.model_dump(),
        owner_id=user.get("id"),
    )

    try:
        todo.description = create_todo_with_gemini(
            todo.description
        )
    except RuntimeError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=str(exc),
        ) from exc
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Gemini request failed",
        ) from exc

    db.add(todo)
    db.commit()


@router.put(
    "/todo/{todo_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def update_todo(
    user: user_dependency,
    db: db_dependency,
    todo_request: TodoRequest,
    todo_id: int = ApiPath(gt=0),
):
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED
        )

    todo = (
        db.query(Todo)
        .filter(
            Todo.id == todo_id,
            Todo.owner_id == user.get("id"),
        )
        .first()
    )

    if todo is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Todo not found",
        )

    todo.title = todo_request.title
    todo.description = todo_request.description
    todo.priority = todo_request.priority
    todo.complete = todo_request.complete

    db.add(todo)
    db.commit()


@router.delete(
    "/todo/{todo_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def delete_todo(
    user: user_dependency,
    db: db_dependency,
    todo_id: int = ApiPath(gt=0),
):
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED
        )

    todo = (
        db.query(Todo)
        .filter(
            Todo.id == todo_id,
            Todo.owner_id == user.get("id"),
        )
        .first()
    )

    if todo is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Todo not found",
        )

    db.delete(todo)
    db.commit()


def markdown_to_text(markdown_string: str) -> str:
    html = markdown.markdown(markdown_string)
    soup = BeautifulSoup(html, "html.parser")
    return soup.get_text()


def create_todo_with_gemini(todo_string: str) -> str:
    if not GOOGLE_API_KEY:
        raise RuntimeError(
            "GOOGLE_API_KEY is not configured. "
            "Add it to your local .env file."
        )

    genai.configure(api_key=GOOGLE_API_KEY)

    llm = ChatGoogleGenerativeAI(
        model=GEMINI_MODEL,
        google_api_key=GOOGLE_API_KEY,
    )

    response = llm.invoke(
        [
            HumanMessage(
                content=(
                    "I will provide you a todo item to add to my "
                    "todo list. Create a longer and more "
                    "comprehensive description of that todo item. "
                    "My next message will be the todo."
                )
            ),
            HumanMessage(content=todo_string),
        ]
    )

    return markdown_to_text(response.content)
