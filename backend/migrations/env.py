"""Alembic setup. Uses the app's own database engine and models, so there is one source of truth."""
import logging.config

from alembic import context

from app import models  # noqa: F401  (registers tables on Base.metadata)
from app.database import Base, engine

config = context.config
target_metadata = Base.metadata

# When run from the command line ("alembic upgrade head"), use the logging setup in alembic.ini.
# When run by the app on startup, keep the app's own logging.
if config.config_file_name and not config.attributes.get("from_app"):
    logging.config.fileConfig(config.config_file_name, disable_existing_loggers=False)


def run_migrations_offline():
    """Print the SQL instead of running it:  alembic upgrade head --sql"""
    context.configure(
        url=engine.url.render_as_string(hide_password=False),
        target_metadata=target_metadata,
        literal_binds=True,
        render_as_batch=engine.dialect.name == "sqlite",
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online():
    with engine.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            # SQLite can't ALTER most things; "batch" mode rebuilds the table instead.
            render_as_batch=connection.dialect.name == "sqlite",
            compare_type=True,
        )
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
