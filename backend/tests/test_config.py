import pytest

from app.config import Settings


@pytest.mark.parametrize("given", [
    "postgres://u:p@host:5432/db?sslmode=require",
    "postgresql://u:p@host:5432/db?sslmode=require",
    "postgresql+psycopg2://u:p@host:5432/db?sslmode=require",
])
def test_database_url_gets_psycopg2_driver(given):
    s = Settings(database_url=given)
    assert s.database_url == "postgresql+psycopg2://u:p@host:5432/db?sslmode=require"
    assert not s.is_sqlite


def test_sqlite_url_unchanged():
    assert Settings(database_url="sqlite:///./x.db").is_sqlite


def test_weak_secret_blocked_on_real_database(monkeypatch):
    from app import main

    monkeypatch.setattr(main, "settings", Settings(database_url="postgres://u:p@h/db", jwt_secret="short"))
    with pytest.raises(RuntimeError, match="JWT_SECRET"):
        main.check_settings()
    monkeypatch.setattr(main, "settings", Settings(database_url="postgres://u:p@h/db", jwt_secret="x" * 40))
    main.check_settings()  # no error
