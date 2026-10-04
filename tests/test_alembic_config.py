from io import StringIO

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy.engine import make_url

from app import database


@pytest.mark.parametrize("url", [
    "postgresql+psycopg://user:pass%40word@localhost/app",
    "postgresql+psycopg://user:pass%25word@localhost/app",
    "postgresql+psycopg://user:password@localhost/app",
    "sqlite:///./test.db",
], ids=["percent40", "percent25", "normal", "sqlite"])
def test_migration_url_round_trip_and_offline_upgrade(url, monkeypatch):
    monkeypatch.setattr(database, "SQLALCHEMY_DATABASE_URL", url)
    output = StringIO()
    config = Config(output_buffer=output)
    config.set_main_option("script_location", "alembic")
    command.upgrade(config, "head", sql=True)
    assert config.get_main_option("sqlalchemy.url") == url
    assert make_url(config.get_main_option("sqlalchemy.url")) == make_url(url)
    assert database.SQLALCHEMY_DATABASE_URL == url
    assert "CREATE TABLE requests" in output.getvalue()
