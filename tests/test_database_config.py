from app.database import normalize_database_url


def test_sqlite_url_is_left_unchanged():
    url = "sqlite:///./test.db"

    assert normalize_database_url(url) == url


def test_postgresql_url_uses_psycopg_v3_driver():
    assert normalize_database_url(
        "postgresql://user:pass@db:5432/app"
    ) == (
        "postgresql+psycopg://user:pass@db:5432/app"
    )


def test_legacy_postgres_url_uses_psycopg_v3_driver():
    assert normalize_database_url(
        "postgres://user:pass@db:5432/app"
    ) == (
        "postgresql+psycopg://user:pass@db:5432/app"
    )


def test_explicit_sqlalchemy_driver_is_preserved():
    url = "postgresql+psycopg://user:pass@db:5432/app"

    assert normalize_database_url(url) == url
