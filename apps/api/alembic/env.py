"""Alembic environment.

Uses the *sync* psycopg driver rather than asyncpg. Migrations are a
short-lived batch process with no concurrency to gain from an event loop, and
the sync path keeps this file about half the size.
"""

from logging.config import fileConfig

from sqlalchemy import engine_from_config, pool

from alembic import context

# Importing the models package registers every table on Base.metadata.
# Without this import autogenerate produces an empty migration.
from app.core.config import get_settings
from app.models import Base

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata

settings = get_settings()
config.set_main_option("sqlalchemy.url", settings.sync_database_url)


def run_migrations_offline() -> None:
    """Emit SQL to stdout without connecting -- for reviewing a migration."""
    context.configure(
        url=settings.sync_database_url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            # Without these, autogenerate misses column type changes and
            # server-default changes -- exactly the edits that silently break
            # a deploy.
            compare_type=True,
            compare_server_default=True,
        )
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
