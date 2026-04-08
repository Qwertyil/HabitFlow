import os

from logging.config import fileConfig

from sqlalchemy import engine_from_config
from sqlalchemy import pool
from sqlalchemy.engine import make_url

from alembic import context

from src.database.models import *  # noqa
from src.database.models.base import BaseModel

config = context.config


if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = BaseModel.metadata


def _normalize_sync_database_url(raw_url: str) -> str:
    url = make_url(raw_url)

    if url.drivername == "postgresql+asyncpg":
        url = url.set(drivername="postgresql+psycopg2")

    return url.render_as_string(hide_password=False)


def _resolve_database_url() -> str:
    configured_url = config.get_main_option("sqlalchemy.url")
    if configured_url and not configured_url.startswith("driver://"):
        return _normalize_sync_database_url(configured_url)

    env_url = os.getenv("DATABASE_URL")
    if env_url:
        return _normalize_sync_database_url(env_url)

    from src.config import load_settings

    return load_settings().DATABASE_URL_psycopg2


config.set_main_option("sqlalchemy.url", _resolve_database_url())


def run_migrations_offline() -> None:
    """Run migrations in 'offline' mode.

    This configures the context with just a URL
    and not an Engine, though an Engine is acceptable
    here as well.  By skipping the Engine creation
    we don't even need a DBAPI to be available.

    Calls to context.execute() here emit the given string to the
    script output.

    """
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )

    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """Run migrations in 'online' mode.

    In this scenario we need to create an Engine
    and associate a connection with the context.

    """
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    with connectable.connect() as connection:
        context.configure(
            connection=connection, target_metadata=target_metadata
        )

        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
