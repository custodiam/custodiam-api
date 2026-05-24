"""Alembic environment configuration.

Lee DATABASE_URL del archivo .env (via python-dotenv) en lugar de usar
el valor hardcodeado de alembic.ini.
Usa SQLModel.metadata (que incluye todos los modelos registrados).
"""

import os
from logging.config import fileConfig

from dotenv import load_dotenv

load_dotenv()  # Cargar .env ANTES de leer DATABASE_URL

from alembic import context
from sqlalchemy import engine_from_config, pool
from sqlmodel import SQLModel

# Importar TODOS los modelos para que SQLModel.metadata los registre
import app.models  # noqa: F401

target_metadata = SQLModel.metadata

config = context.config

# Sobreescribir sqlalchemy.url con DATABASE_URL del entorno
database_url = os.getenv("DATABASE_URL")
if database_url:
    config.set_main_option("sqlalchemy.url", database_url)

if config.config_file_name is not None:
    fileConfig(config.config_file_name)


def run_migrations_offline() -> None:
    """Run migrations in 'offline' mode."""
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
    """Run migrations in 'online' mode."""
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
        )

        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
