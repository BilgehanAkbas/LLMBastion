from sqlalchemy import create_engine
from sqlalchemy.orm import declarative_base, sessionmaker

from .core.config import DATABASE_URL


def normalize_database_url(url: str) -> str:
    """Use psycopg v3 for standard PostgreSQL URLs.

    Many deployment platforms provide postgresql:// or legacy postgres://
    URLs. SQLAlchemy needs an explicit psycopg driver because this project
    intentionally uses psycopg v3 rather than psycopg2.
    """
    if url.startswith("postgres://"):
        return "postgresql+psycopg://" + url[len("postgres://"):]
    if url.startswith("postgresql://"):
        return (
            "postgresql+psycopg://"
            + url[len("postgresql://"):]
        )
    return url


SQLALCHEMY_DATABASE_URL = normalize_database_url(DATABASE_URL)

engine_options = {
    "pool_pre_ping": True,
}

if SQLALCHEMY_DATABASE_URL.startswith("sqlite"):
    engine_options["connect_args"] = {
        "check_same_thread": False,
    }

engine = create_engine(
    SQLALCHEMY_DATABASE_URL,
    **engine_options,
)

SessionLocal = sessionmaker(
    autocommit=False,
    autoflush=False,
    bind=engine,
)

Base = declarative_base()
