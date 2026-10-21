"""Database connection. SQLAlchemy talks to SQLite locally or Postgres in production."""
import logging
from pathlib import Path

from sqlalchemy import create_engine, inspect, text
from sqlalchemy.orm import DeclarativeBase, sessionmaker

from .config import get_settings

log = logging.getLogger(__name__)
settings = get_settings()
BACKEND_DIR = Path(__file__).resolve().parents[1]

if settings.is_sqlite:
    engine = create_engine(settings.database_url, connect_args={"check_same_thread": False})
else:
    engine = create_engine(
        settings.database_url,
        pool_pre_ping=True,  # hosted Postgres (e.g. Neon) closes idle connections; test before use
        pool_size=5,
        max_overflow=5,
        pool_recycle=300,
    )
SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


class Base(DeclarativeBase):
    pass


def get_db():
    """FastAPI dependency: opens a DB session per request and always closes it."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def _alembic_config():
    from alembic.config import Config

    cfg = Config(str(BACKEND_DIR / "alembic.ini"))
    cfg.set_main_option("script_location", str(BACKEND_DIR / "migrations"))
    cfg.attributes["from_app"] = True
    return cfg


def init_db():
    """Create or update all tables by running the database migrations.

    This runs every time the app starts. It is safe to run many times:
    Alembic remembers which migrations are done (in the "alembic_version" table)
    and only runs new ones.
    """
    from alembic import command

    from . import models  # noqa: F401  (registers tables)

    cfg = _alembic_config()
    tables = set(inspect(engine).get_table_names())
    if "users" in tables and "alembic_version" not in tables:
        # Database was made by an early version that used create_all(). Mark it as up to date.
        log.info("Existing tables found without migration history. Marking them as the first migration.")
        command.stamp(cfg, "0001_initial")
    command.upgrade(cfg, "head")


def check_db() -> bool:
    try:
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        return True
    except Exception:  # noqa: BLE001
        log.exception("Database check failed")
        return False
