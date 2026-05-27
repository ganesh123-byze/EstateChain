"""Alembic environment configuration.

This project uses raw psycopg2 for application queries. Alembic is configured
with a SQLAlchemy engine purely for migration execution; revision scripts use
`op.execute()` with raw SQL (not ORM model autogenerate).
"""
import os
import sys

from alembic import context
from sqlalchemy import engine_from_config, pool

# Ensure project root is on path so backend.* imports work
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))

from backend.config.settings import get_database_url

# this is the Alembic Config object, which provides
# access to the values within the .ini file in use.
config = context.config

# Override sqlalchemy.url with the real DATABASE_URL from settings.
# ConfigParser treats "%" as interpolation; escape for passwords like Ganesh@29327 → %40.
config.set_main_option("sqlalchemy.url", get_database_url().replace("%", "%%"))

# add your model's MetaData object here for 'autogenerate' support
# (Not applicable — this project uses raw psycopg2, not SQLAlchemy ORM.)
target_metadata = None


def run_migrations_offline() -> None:
    """Run migrations in 'offline' mode.

    This configures the context with just a URL and not an Engine.
    Calls to context.execute() here emit the given string to the script output.
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

    In this scenario we need to create an Engine and associate a connection
    with the context.
    """
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    with connectable.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata)

        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
